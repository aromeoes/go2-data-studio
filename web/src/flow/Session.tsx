/**
 * Session: camera first, map second, recording and controls above the fold;
 * recordings and robot actions below it. Teleop is always available: keys,
 * the touch pad or L1 take control directly, with no Enable button.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Circle, Menu } from "lucide-react";
import { robot } from "../sdk";
import type { State } from "../types";
import { MapCanvas } from "../MapCanvas";
import { BackupControl } from "../Cloud";
import { UnitreeActions } from "../UnitreeActions";
import { VectorSensors } from "../VectorSensors";
import { RobotSkillStatus } from "../RobotSkillStatus";
import { HumanCLIHelp } from "../HumanCLIHelp";
import { HumanCLISettings } from "../HumanCLISettings";
import { useControllerTakeover } from "../useControllerTakeover";
import { useControllerStop } from "../useControllerStop";
import { embodiment } from "./modules";
import { Sidebar } from "./Sidebar";
import { api, cameraLive, Dialog, dialogOpen, gb, useStreamRate, type Notify } from "./ui";

const DRIVE_KEYS = ["w", "a", "s", "d", "q", "e", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
/** Keyboard control is handed back after this long without input, so other actions can run. */
const IDLE_RELEASE_MS = 2500;
const POPUP = "humancli-has-control";
const PAD = [
  [["q", "Left"], ["w", "Forward"], ["e", "Right"]],
  [["a", "Turn left"], ["s", "Back"], ["d", "Turn right"]],
];
const date = (s: number) => new Date(s * 1000).toLocaleString("en-US", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export function Session({
  state,
  robotName,
  spaceId,
  onSpace,
  notify,
  onEnded,
}: {
  state: State;
  robotName: string;
  spaceId: string;
  onSpace: (id: string) => void;
  notify: Notify;
  onEnded: () => void;
}) {
  const kind = state.robot_kind || "go2";
  const selected = state.selected_modules || [];
  const has = (id: string) => selected.includes(id);
  const blueprint = embodiment(kind).blueprints.find((b) => b.id === state.profile?.preset)?.name || "Custom";
  const [tab, setTab] = useState<"teleop" | "agent">("teleop");
  const [archive, setArchive] = useState<"recordings" | "maps" | "activity">("recordings");
  const [speed, setSpeed] = useState(kind === "vector" ? 0.1 : 0.5);
  const [pressed, setPressed] = useState<string[]>([]);
  const [popup, setPopup] = useState(false);
  const [menu, setMenu] = useState(false);
  const [ending, setEnding] = useState(false);
  const [chat, setChat] = useState("");
  const [busy, setBusy] = useState("");
  const held = useRef<number | null>(null);
  const keys = useRef(new Set<string>());
  const acquiring = useRef(false);
  const idleTimer = useRef<number | undefined>(undefined);
  const online = state.connection === "online";
  const estop = !!state.telemetry.control?.estop;
  const working =
    state.mode === "agent" && (state.agent.busy || state.telemetry.skills?.phase === "running" || !!state.telemetry.path);
  const live = useRef({ online, estop, hold: !!state.hold, working, speed, mode: state.mode });
  live.current = { online, estop, hold: !!state.hold, working, speed, mode: state.mode };
  const space = state.spaces.find((s) => s.id === spaceId);
  const rate = useStreamRate();

  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      await fn();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };

  // ------------------------------------------------------------ driving

  const release = () => {
    clearTimeout(idleTimer.current);
    const epoch = held.current;
    held.current = null;
    robot.disarm();
    if (epoch !== null) void api("/release", { epoch }).catch(() => {});
  };

  const acquire = async (source: "keyboard" | "controller") => {
    if (robot.inputSource !== source) robot.selectInput(source);
    const result = await api("/mode", { mode: "teleop" });
    held.current = result.epoch;
    robot.arm(live.current.speed);
    setTab("teleop");
  };

  const blockedReason = () => {
    const s = live.current;
    return !s.online ? "Not connected." : s.estop ? "Stopped. Release stop to drive." : s.hold ? "Movement is off. Turn it on to drive." : "";
  };

  const press = (key: string) => {
    const reason = blockedReason();
    if (reason) return notify(reason);
    if (live.current.working) return setPopup(true);
    clearTimeout(idleTimer.current);
    keys.current.add(key);
    setPressed([...keys.current]);
    if (held.current !== null && live.current.mode === "teleop" && robot.inputSource === "keyboard") {
      robot.keys(keys.current);
      return;
    }
    if (acquiring.current) return;
    acquiring.current = true;
    acquire("keyboard")
      .then(() => robot.keys(keys.current))
      .catch((e) => {
        keys.current.clear();
        setPressed([]);
        notify(e.message, "error");
      })
      .finally(() => (acquiring.current = false));
  };

  const unpress = (key: string) => {
    if (!keys.current.delete(key)) return;
    setPressed([...keys.current]);
    robot.keys(keys.current);
    if (!keys.current.size)
      idleTimer.current = window.setTimeout(() => {
        if (!keys.current.size && live.current.mode === "teleop" && robot.inputSource === "keyboard") release();
      }, IDLE_RELEASE_MS);
  };

  const halt = () => {
    keys.current.clear();
    setPressed([]);
    held.current = null;
    robot.machine?.estop();
    robot.disarm();
    api("/stop")
      .then(() => notify("Stopped. The robot holds its position."))
      .catch((e) => notify(e.message, "error"));
  };

  const controls = useRef({ press, unpress, halt, release });
  controls.current = { press, unpress, halt, release };

  useEffect(() => {
    const keyOf = (e: KeyboardEvent) => (e.code.startsWith("Key") ? e.code.slice(3).toLowerCase() : e.key);
    const typing = (e: KeyboardEvent) => e.target instanceof HTMLElement && e.target.matches("input, textarea, select, [contenteditable=true]");
    const down = (e: KeyboardEvent) => {
      if (typing(e) || dialogOpen()) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (!e.repeat) controls.current.halt();
        return;
      }
      const key = keyOf(e);
      if (!DRIVE_KEYS.includes(key)) return;
      e.preventDefault();
      if (!e.repeat) controls.current.press(key);
    };
    const up = (e: KeyboardEvent) => controls.current.unpress(keyOf(e));
    const blur = () => {
      keys.current.clear();
      setPressed([]);
      if (held.current !== null && live.current.mode === "teleop") controls.current.release();
    };
    const hidden = () => document.hidden && blur();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", hidden);
      controls.current.release();
    };
  }, []);

  // The control lease stays valid only while heartbeats arrive.
  useEffect(() => {
    const id = setInterval(() => {
      const epoch = held.current;
      if (epoch === null) return;
      api("/heartbeat", { epoch })
        .then((r) => {
          if (!r.ok && held.current === epoch) {
            held.current = null;
            robot.disarm();
          }
        })
        .catch(() => {});
    }, 250);
    return () => clearInterval(id);
  }, []);

  // Control ended elsewhere (Stop, lease expiry, sensor guard): forget the lease.
  useEffect(() => {
    if (state.mode === "idle" && held.current !== null && state.epoch > held.current) {
      held.current = null;
      robot.disarm();
    }
  }, [state.mode, state.epoch]);

  useControllerTakeover({
    enabled: () => live.current.online && !live.current.estop && !live.current.hold && !dialogOpen(),
    speed: () => live.current.speed,
    kind: () => kind,
    input: (value) => robot.gamepad(value),
    stop: () => robot.disarm(),
    error: (message) => message !== POPUP && notify(message, "error"),
    take: async () => {
      if (live.current.working) {
        setPopup(true);
        throw Error(POPUP);
      }
      await acquire("controller");
      return () => controls.current.release();
    },
  });
  useControllerStop(() => !dialogOpen(), () => controls.current.halt());

  // --------------------------------------------------------- notifications

  const previous = useRef(state.connection);
  useEffect(() => {
    const before = previous.current;
    previous.current = state.connection;
    if (before === "online" && state.connection === "reconnecting") notify(state.error || "Connection lost. Reconnecting.", "error");
    if (before === "reconnecting" && state.connection === "online") notify(`${robotName} reconnected. Modules restarted.`);
  }, [state.connection]);

  const stale = useRef<Record<string, boolean>>({});
  const latest = useRef(state);
  latest.current = state;
  useEffect(() => {
    const id = setInterval(() => {
      const s = latest.current;
      if (s.connection !== "online") return;
      const streams = [
        ["color_image", "Camera", s.profile?.enabled.includes("camera")],
        ["lidar", "LiDAR", kind === "go2" && s.profile?.enabled.includes("lidar")],
      ] as const;
      for (const [key, label, on] of streams) {
        if (!on) continue;
        const sample = s.telemetry.sensors?.[key];
        const isStale = !sample || Date.now() / 1000 - sample.received > 3;
        if (isStale && !stale.current[key]) notify(`${label} data stopped arriving.`, "error");
        if (!isStale && stale.current[key]) notify(`${label} data is back.`);
        stale.current[key] = isStale;
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // ------------------------------------------------------------- actions

  const toTeleop = () => {
    if (state.mode === "agent") release();
    setTab("teleop");
  };
  const toAgent = () =>
    run("agent-mode", async () => {
      keys.current.clear();
      setPressed([]);
      robot.disarm();
      const result = await api("/mode", { mode: "agent" });
      held.current = result.epoch;
      setTab("agent");
    });

  const send = (e: FormEvent) => {
    e.preventDefault();
    const text = chat.trim();
    if (!text) return;
    void run("agent", async () => {
      if (state.mode !== "agent" || held.current === null) {
        const result = await api("/mode", { mode: "agent" });
        held.current = result.epoch;
      }
      await api("/agent", { text, epoch: held.current, space_id: spaceId || null });
      setChat("");
    });
  };

  const pauseControl = async () => {
    held.current = null;
    robot.disarm();
    if (state.mode !== "idle") await api("/mode", { mode: "idle" });
  };

  const end = () =>
    run("end", async () => {
      const recording = !!state.session;
      await pauseControl().catch(() => {});
      if (recording) await api("/record/stop");
      await api("/disconnect");
      setEnding(false);
      notify(recording ? "Session ended. Recording saved." : "Session ended.");
      onEnded();
    });

  // ------------------------------------------------------------- render

  const cameraOn = cameraLive(state);
  const mapping = !!state.profile?.enabled.includes("mapping");
  const canRecord = has("ConsoleBridge");
  const stats = state.stats;
  const sessions = state.sessions.filter((s) => s.parent === spaceId);
  const segments = state.segments.filter((s) => sessions.some((x) => x.id === s.parent));
  const maps = state.maps.filter((m) => segments.some((s) => s.id === m.parent));
  const messages = state.agent.messages.filter((m) => Date.now() / 1000 - m.ts < 1800).slice(-12);
  const battery =
    kind === "vector"
      ? state.telemetry.vector?.power
        ? `${state.telemetry.vector.power.volts.toFixed(2)} V`
        : "Battery n/a"
      : typeof state.telemetry.battery?.percent === "number"
        ? `${state.telemetry.battery.percent}%`
        : "Battery n/a";

  return (
    <main className="screen session">
      <header className="bar">
        <button className="icon-button" aria-label="Open menu" onClick={() => setMenu(true)}>
          <Menu size={18} />
        </button>
        <strong>{robotName}</strong>
        <span className="tag">{blueprint}</span>
        <span className="spacer" />
        <span className="muted">{battery}</span>
        <span className={"status " + state.connection}>{online ? "Connected" : state.connection === "reconnecting" ? "Reconnecting" : "Connecting"}</span>
        <button onClick={() => setEnding(true)}>End session</button>
      </header>

      <div className="session-grid">
        <section className="card camera" aria-label="Camera">
          {cameraOn ? <img src={robot.camera} alt={`${robotName} front camera`} /> : <div className="no-signal">No camera signal</div>}
          {cameraOn && (
            <span className="live-badge">
              ● LIVE · {rate.fps} fps · {rate.kbps} kB/s
            </span>
          )}
        </section>

        <div className="side">
          <section className="card map" aria-label="Map">
            {mapping ? (
              <MapCanvas grid={state.telemetry.map} pose={state.telemetry.pose} path={state.telemetry.path} />
            ) : (
              <div className="no-signal">{kind === "vector" ? "No map: Vector has no LiDAR." : "Map needs VoxelGridMapper and CostMapper."}</div>
            )}
          </section>

          <section className="card control" aria-label="Controls">
            <div className="row">
              <div className="tabs" role="tablist">
                <button role="tab" aria-selected={tab === "teleop"} onClick={toTeleop}>
                  Teleop
                </button>
                {has("McpClient") && (
                  <button role="tab" aria-selected={tab === "agent"} disabled={!!busy} onClick={() => void toAgent()}>
                    HumanCLI
                  </button>
                )}
              </div>
              <span className="spacer" />
              <label className="switch" title="When off, the robot stays in place">
                <input
                  type="checkbox"
                  role="switch"
                  checked={!state.hold}
                  disabled={!online || !!busy}
                  onChange={(e) => {
                    const on = e.target.checked;
                    void run("hold", async () => {
                      if (!on) await pauseControl();
                      await api("/hold", { on: !on });
                      notify(on ? "Movement on." : "Movement off. The robot stays in place.");
                    });
                  }}
                />
                Movement
              </label>
            </div>
            {estop && (
              <div className="banner">
                Stopped.
                <button onClick={() => void run("clear", () => api("/clear"))}>Release stop</button>
              </div>
            )}
            {state.hold && <p className="banner">Movement is off. The robot stays in place.</p>}

            {tab === "teleop" ? (
              <div className="teleop">
                <p className="muted">
                  {pressed.length ? "Driving" : "Ready to drive"} · Keyboard: W/S forward and back, A/D turn
                  {kind !== "vector" && ", Q/E sideways"} · Steam Deck: hold L1 · Stop: Space or B
                </p>
                <div className="pad">
                  {PAD.flat()
                    .filter(([key]) => kind !== "vector" || !["q", "e"].includes(key))
                    .map(([key, label]) => (
                      <button
                        key={key}
                        className={pressed.includes(key) ? "on" : ""}
                        onPointerDown={(e) => {
                          e.currentTarget.setPointerCapture(e.pointerId);
                          press(key);
                        }}
                        onPointerUp={() => unpress(key)}
                        onPointerCancel={() => unpress(key)}
                      >
                        <kbd>{key.toUpperCase()}</kbd> {label}
                      </button>
                    ))}
                </div>
                <label className="inline">
                  Speed
                  <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                    {(kind === "vector" ? [0.05, 0.1, 0.15] : [0.3, 0.5, 0.8]).map((v) => (
                      <option key={v} value={v}>
                        {v} m/s
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            ) : (
              <div className="agent">
                {!state.agent.model?.configured && (
                  <HumanCLISettings config={state.agent.model} pending={!!busy} save={(value) => run("agent-config", () => api("/agent/config", value))} />
                )}
                <div className="row">
                  <HumanCLIHelp capabilities={state.agent.capabilities || []} />
                  <span className="spacer" />
                  <button className="link" onClick={() => void run("conversation", () => api("/agent/conversation"))}>
                    New conversation
                  </button>
                </div>
                <RobotSkillStatus state={state.telemetry.skills} />
                <div className="messages" role="log" aria-label="HumanCLI conversation">
                  {messages.length ? (
                    messages.map((m, i) => (
                      <p key={i} className={"message " + m.role}>
                        <small>{m.role === "user" ? "You" : m.role === "tool" ? "Tool" : "HumanCLI"}</small>
                        {m.text}
                      </p>
                    ))
                  ) : (
                    <p className="muted">Try “explore this room”, “remember this as reception” or “go to reception”.</p>
                  )}
                </div>
                {state.agent.busy && (
                  <p className="muted">
                    HumanCLI is working…{" "}
                    <button className="link" onClick={() => void run("cancel", () => api("/agent/cancel"))}>
                      Cancel
                    </button>
                  </p>
                )}
                <form className="row" onSubmit={send}>
                  <input aria-label="HumanCLI instruction" value={chat} onChange={(e) => setChat(e.target.value)} placeholder="Tell the robot what to do" />
                  <button className="primary" disabled={!chat.trim() || state.agent.busy || !!busy}>
                    Send
                  </button>
                </form>
              </div>
            )}
          </section>
        </div>

        <section className={"card record" + (state.session ? " recording" : "")} aria-label="Recording">
          <Circle size={16} fill={state.session ? "currentColor" : "none"} />
          <div>
            <strong>{state.session ? "Recording" : "Record your exploration"}</strong>
            <span className="muted">
              Space: {space?.name || "none"}
              {!state.session && (
                <button className="link" onClick={() => setMenu(true)}>
                  Change
                </button>
              )}
            </span>
          </div>
          <dl className="numbers">
            <dt>LiDAR</dt>
            <dd>{gb(stats?.streams.lidar?.bytes)} GB</dd>
            <dt>Camera</dt>
            <dd>{gb(stats?.streams.color_image?.bytes)} GB</dd>
            <dt>Total</dt>
            <dd>{gb(stats?.physical_bytes)} GB</dd>
            <dt>Rate</dt>
            <dd>{(stats?.gb_per_min || 0).toFixed(2)} GB/min</dd>
          </dl>
          <button
            className={state.session ? "danger" : "primary"}
            disabled={!!busy || !online || !canRecord || !space}
            title={canRecord ? undefined : "Recording needs ConsoleBridge in the blueprint"}
            onClick={() => void run("record", () => api(state.session ? "/record/stop" : "/record/start", { space_id: spaceId }))}
          >
            {state.session ? "Save recording" : "Record"}
          </button>
        </section>
      </div>

      <section className="card archive" aria-label="Saved data">
        <div className="tabs" role="tablist">
          {(
            [
              ["recordings", `Recordings (${segments.length})`],
              ["maps", `Generated maps (${maps.length})`],
              ["activity", "Activity"],
            ] as const
          ).map(([id, label]) => (
            <button key={id} role="tab" aria-selected={archive === id} onClick={() => setArchive(id)}>
              {label}
            </button>
          ))}
        </div>
        {archive === "recordings" && (
          <ul className="list">
            {segments.map((s, i) => (
              <li key={s.id}>
                <div>
                  <strong>Segment {segments.length - i}</strong>
                  <small>
                    {date(s.created)} · {gb(s.stats?.physical_bytes)} GB · {((s.stats?.duration || 0) / 60).toFixed(1)} min · {s.status}
                  </small>
                </div>
                <BackupControl segment={s} spaceName={space?.name} cloud={state.cloud} action={run} api={api} pending={!!busy} />
                <button
                  disabled={!!busy || s.status === "recording"}
                  onClick={() =>
                    void run("map", async () => {
                      await pauseControl();
                      await api("/maps", { segment_id: s.id, voxel: 0.1, pgo: true });
                      setArchive("maps");
                      notify("Generating the map on this device.");
                    })
                  }
                >
                  Generate map
                </button>
              </li>
            ))}
            {!segments.length && <li className="muted">No recordings in {space?.name || "this space"} yet.</li>}
          </ul>
        )}
        {archive === "maps" && (
          <ul className="list">
            {maps.map((m, i) => (
              <li key={m.id}>
                <div>
                  <strong>Map {maps.length - i}</strong>
                  <small>
                    {date(m.created)} · {m.status}
                    {m.error ? ` · ${m.error}` : ""}
                  </small>
                </div>
                {["queued", "running"].includes(m.status) && <button onClick={() => void run("cancel-map", () => api(`/maps/${m.id}/cancel`))}>Cancel</button>}
              </li>
            ))}
            {!maps.length && <li className="muted">Generate a map from a recording.</li>}
          </ul>
        )}
        {archive === "activity" && (
          <ul className="list">
            {state.events.map((e) => (
              <li key={e.id}>
                <small>{date(e.ts)}</small> {e.message}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card robot-actions" aria-label="Robot actions">
        {kind === "vector" ? (
          <VectorSensors data={state.telemetry.vector} connected={online} />
        ) : (
          <>
            <h2>Robot actions</h2>
            <div className="row">
              <button disabled={!online || !!busy} onClick={() => void run("stand", () => api("/posture/stand"))}>
                Stand up
              </button>
              <button disabled={!online || !!busy} onClick={() => void run("lie", () => api("/posture/lie"))}>
                Lie down
              </button>
            </div>
            {has("UnitreeSkillContainer") && (
              <UnitreeActions connected={online} mode={state.mode} stopped={estop} epoch={state.epoch} enabled={!!state.profile?.enabled.includes("teleop")} api={api} />
            )}
          </>
        )}
      </section>

      {menu && <Sidebar state={state} spaceId={spaceId} onSpace={onSpace} notify={notify} onClose={() => setMenu(false)} />}
      {popup && (
        <Dialog label="HumanCLI is controlling the robot" onClose={() => setPopup(false)}>
          <h2>HumanCLI is controlling the robot</h2>
          <p>Switch to Teleop to stop HumanCLI and drive yourself.</p>
          <button
            className="primary"
            autoFocus
            onClick={() => {
              setPopup(false);
              void run("takeover", async () => {
                await acquire(robot.inputSource);
                notify("Teleop has control. HumanCLI stopped.");
              });
            }}
          >
            Switch to Teleop
          </button>
          <button onClick={() => setPopup(false)}>Keep HumanCLI</button>
        </Dialog>
      )}
      {ending && (
        <Dialog label="End session" onClose={() => setEnding(false)}>
          <h2>End session?</h2>
          <p>{state.session ? "The recording is saved, then the robot disconnects." : "The robot disconnects."} You go back to your robots.</p>
          <button className="primary" autoFocus disabled={!!busy} onClick={() => void end()}>
            End session
          </button>
          <button onClick={() => setEnding(false)}>Keep going</button>
        </Dialog>
      )}
    </main>
  );
}
