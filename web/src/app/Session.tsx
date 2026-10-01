/**
 * Session: camera first, map second, recording and controls above the fold;
 * recordings, maps, robot actions and diagnostics below it. Teleop is always
 * available: keys, the touch pad or L1 take control directly.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Circle, Copy, LoaderCircle, Menu, Mic, Play } from "lucide-react";
import { robot } from "../sdk";
import type { State } from "../types";
import { MapCanvas } from "../MapCanvas";
import { UnitreeActions } from "../UnitreeActions";
import { VectorSensors } from "../VectorSensors";
import { RobotSkillStatus } from "../RobotSkillStatus";
import { NavigationPanel } from "../RobotStatus";
import { HumanCLIHelp } from "../HumanCLIHelp";
import { HumanCLISettings } from "../HumanCLISettings";
import { ControllerDiagram } from "../ControllerDiagram";
import { useControllerTakeover } from "../useControllerTakeover";
import { useControllerStop } from "../useControllerStop";
import { usePushToTalk } from "../usePushToTalk";
import { hasModule } from "./modules";
import { Archive } from "./Archive";
import { Sidebar } from "./Sidebar";
import { api, cameraLive, Dialog, dialogOpen, gb, useStreamRate, type Notify } from "./ui";

const DRIVE_KEYS = ["w", "a", "s", "d", "q", "e", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
/** Keyboard control is handed back after this long without input, so other actions can run. */
const IDLE_RELEASE_MS = 2500;
const POPUP = "humancli-has-control";
const PAD = [
  ["q", "Left"],
  ["w", "Forward"],
  ["e", "Right"],
  ["a", "Turn left"],
  ["s", "Back"],
  ["d", "Turn right"],
];

export function Session({
  state,
  robotName,
  blueprintName,
  spaceId,
  onSpace,
  notify,
  onEnded,
}: {
  state: State;
  robotName: string;
  blueprintName: string;
  spaceId: string;
  onSpace: (id: string) => void;
  notify: Notify;
  onEnded: () => void;
}) {
  const kind = state.robot_kind || "go2";
  const has = (id: string) => hasModule(state.selected_modules, id);
  const enabled = (capability: string) => !!state.profile?.enabled.includes(capability);
  const [tab, setTab] = useState<"teleop" | "agent">("teleop");
  const [speed, setSpeed] = useState(kind === "vector" ? 0.1 : 0.5);
  const [pressed, setPressed] = useState<string[]>([]);
  const [popup, setPopup] = useState(false);
  const [menu, setMenu] = useState(false);
  const [ending, setEnding] = useState(false);
  const [chat, setChat] = useState("");
  const [busy, setBusy] = useState("");
  const endingNow = useRef(false);
  endingNow.current = busy === "end";
  const held = useRef<number | null>(null);
  const keys = useRef(new Set<string>());
  const acquiring = useRef(false);
  const idleTimer = useRef<number | undefined>(undefined);
  const online = state.connection === "online";
  const estop = !!state.telemetry.control?.estop;
  const working =
    state.mode === "agent" && (state.agent.busy || state.telemetry.skills?.phase === "running" || !!state.telemetry.path?.length);
  const live = useRef({ online, estop, hold: !!state.hold, working, speed, mode: state.mode, epoch: state.epoch });
  live.current = { online, estop, hold: !!state.hold, working, speed, mode: state.mode, epoch: state.epoch };
  const space = state.spaces.find((s) => s.id === spaceId);
  const rate = useStreamRate();

  // The SDK drops sideways input and uses Vector's turn rate for a Vector.
  useEffect(() => {
    robot.embodiment = kind;
    setSpeed(kind === "vector" ? 0.1 : 0.5);
  }, [kind]);

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
    if (live.current.estop) await api("/clear");
    const result = await api("/mode", { mode: "teleop" });
    held.current = result.epoch;
    robot.arm(live.current.speed);
    setTab("teleop");
  };

  const blockedReason = () => {
    const s = live.current;
    return !s.online ? "Not connected." : s.hold ? "Movement is off. Turn it on to drive." : "";
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
    voice.capture.cancel();
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
    const typing = (e: KeyboardEvent) =>
      e.target instanceof HTMLElement && e.target.matches("input, textarea, select, [contenteditable=true]");
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
    enabled: () => live.current.online && !live.current.hold && !dialogOpen() && !voice.active,
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
      voice.capture.cancel();
      await acquire("controller");
      return () => controls.current.release();
    },
  });
  useControllerStop(() => !dialogOpen(), () => controls.current.halt());

  // ------------------------------------------------------------ HumanCLI

  const enterAgent = async () => {
    keys.current.clear();
    setPressed([]);
    robot.disarm();
    if (live.current.estop) await api("/clear");
    const result = await api("/mode", { mode: "agent" });
    held.current = result.epoch;
    setTab("agent");
    return result.epoch as number;
  };

  const voice = usePushToTalk(
    {
      begin: async () => {
        const s = live.current;
        if (!enabled("voice")) throw Error("Voice input is not part of this session.");
        if (!s.online) throw Error("Connect your robot before speaking.");
        const model = state.agent.model;
        if (!model?.configured || model.provider !== "openai" || model.base_url)
          throw Error("Configure OpenAI in the HumanCLI model settings to use voice.");
        if (state.agent.busy) throw Error("Wait for HumanCLI to finish before speaking.");
        if (dialogOpen()) throw Error("Finish the current dialog first.");
        return enterAgent();
      },
      valid: (epoch) => held.current === epoch && live.current.online && live.current.epoch <= epoch,
      release: (epoch) => {
        if (held.current === epoch) held.current = null;
        void api("/release", { epoch }).catch(() => {});
      },
      submit: async (text, epoch) => {
        setTab("agent");
        await api("/agent", { text, epoch, space_id: spaceId || null });
      },
    },
    () => robot.inputSource === "controller" && enabled("voice"),
  );

  const toTeleop = () => {
    if (state.mode === "agent") release();
    setTab("teleop");
  };
  const toAgent = () => run("agent-mode", enterAgent);

  const send = (e: FormEvent) => {
    e.preventDefault();
    const text = chat.trim();
    if (!text) return;
    void run("agent", async () => {
      if (state.mode !== "agent" || held.current === null) await enterAgent();
      await api("/agent", { text, epoch: held.current, space_id: spaceId || null });
      setChat("");
    });
  };

  // --------------------------------------------------------- notifications

  const previous = useRef(state.connection);
  useEffect(() => {
    const before = previous.current;
    previous.current = state.connection;
    if (endingNow.current) return;
    if (before === "online" && state.connection === "reconnecting") notify(state.error || "Connection lost. Reconnecting.", "error");
    if (before === "reconnecting" && state.connection === "online") notify(`${robotName} reconnected.`);
  }, [state.connection]);

  const lastError = useRef(state.error);
  useEffect(() => {
    if (state.error && state.error !== lastError.current && state.connection === "online") notify(state.error, "error");
    lastError.current = state.error;
  }, [state.error]);

  const stale = useRef<Record<string, boolean>>({});
  const latest = useRef(state);
  latest.current = state;
  useEffect(() => {
    const id = setInterval(() => {
      const s = latest.current;
      // Streams stop on purpose while the session ends.
      if (s.connection !== "online" || endingNow.current) return;
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

  const pauseControl = async () => {
    held.current = null;
    voice.capture.cancel();
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

  const copy = async (path?: string) => {
    if (!path) return;
    await navigator.clipboard.writeText(path);
    notify("Path copied");
  };

  // ------------------------------------------------------------- render

  const cameraOn = cameraLive(state);
  const mapping = enabled("mapping");
  const canRecord = has("ConsoleBridge") && enabled("recording");
  const stats = state.stats;
  const messages = state.agent.messages.filter((m) => Date.now() / 1000 - m.ts < 1800).slice(-12);
  const battery =
    kind === "vector"
      ? state.telemetry.vector?.power
        ? `${state.telemetry.vector.power.volts.toFixed(2)} V`
        : "Battery n/a"
      : typeof state.telemetry.battery?.percent === "number"
        ? `${state.telemetry.battery.percent}%${state.replay ? " · replay" : ""}`
        : "Battery n/a";

  return (
    <main className="screen session">
      {voice.active && (
        <div className="overlay" role="status" aria-live="polite">
          <section className="dialog loading" role="dialog" aria-modal="true" aria-label="Voice input">
            <span className="spinner">
              {voice.phase === "recording" ? <Mic size={20} /> : <LoaderCircle size={20} className="spin" />}
              {voice.phase === "recording" ? "Listening" : voice.phase === "transcribing" ? "Transcribing" : "Getting ready"}
            </span>
            <p>
              {voice.phase === "recording"
                ? "Release R1 to send"
                : voice.phase === "transcribing"
                  ? "Sending your words to HumanCLI"
                  : "Opening microphone"}
            </p>
            <button onClick={() => voice.capture.cancel()}>Cancel · B / Esc</button>
          </section>
        </div>
      )}
      <header className="bar">
        <button className="icon-button" aria-label="Open menu" onClick={() => setMenu(true)}>
          <Menu size={18} />
        </button>
        <strong>{robotName}</strong>
        <span className="tag">{blueprintName}</span>
        {state.replay && (
          <span className="replay-note" title="Controls do not move a physical robot.">
            <Play size={13} /> Playing recorded data. Controls do not move a physical robot.
          </span>
        )}
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
                {has("McpClient") && enabled("humancli") && (
                  <button role="tab" aria-selected={tab === "agent"} disabled={!!busy || !online} onClick={() => void toAgent()}>
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
            {state.telemetry.control?.stop_reason && !estop && <p className="hint" role="status">{state.telemetry.control.stop_reason}</p>}

            {tab === "teleop" ? (
              <div className="teleop">
                <p className="muted">
                  {pressed.length ? "Driving" : "Ready to drive"} · Keyboard: W/S forward and back, A/D turn
                  {kind !== "vector" && ", Q/E sideways"} · Steam Deck: hold L1{kind !== "vector" && ", L2 for 1.0 m/s"} · Stop: Space or B
                </p>
                <div className="pad">
                  {PAD.filter(([key]) => kind !== "vector" || !["q", "e"].includes(key)).map(([key, label]) => (
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
                    {(kind === "vector"
                      ? [
                          [0.05, "0.05 m/s · Slow"],
                          [0.1, "0.10 m/s · Default"],
                          [0.12, "0.12 m/s · Fast"],
                        ]
                      : [
                          [0.25, "0.25 m/s · Slow"],
                          [0.5, "0.5 m/s · Default"],
                          [1, "1.0 m/s · Boost"],
                        ]
                    ).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <details>
                  <summary>Controller layout</summary>
                  <ControllerDiagram />
                </details>
              </div>
            ) : (
              <div className="agent">
                <details open={!state.agent.model?.configured}>
                  <summary>
                    Model ·{" "}
                    {state.agent.model?.configured ? `${state.agent.model.provider} / ${state.agent.model.model}` : "not configured"}
                  </summary>
                  <HumanCLISettings
                    config={state.agent.model}
                    pending={!!busy || state.agent.busy || voice.active}
                    save={(value) => run("agent-config", () => api("/agent/config", value))}
                  />
                </details>
                <div className="row">
                  <HumanCLIHelp capabilities={state.agent.capabilities || []} />
                  <span className="spacer" />
                  <button className="link" onClick={() => void run("conversation", () => api("/agent/conversation"))}>
                    New conversation
                  </button>
                </div>
                {enabled("navigation") && <NavigationPanel navigation={state.telemetry.navigation} />}
                {kind !== "vector" && <RobotSkillStatus state={state.telemetry.skills} />}
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
                {enabled("voice") && (
                  <div className="row">
                    <button
                      aria-label="Hold to talk to HumanCLI"
                      className={voice.phase === "recording" ? "on" : ""}
                      disabled={!online || !!busy || voice.phase === "transcribing"}
                      onPointerDown={(event) => {
                        if (event.button !== 0) return;
                        event.currentTarget.setPointerCapture(event.pointerId);
                        void voice.capture.start();
                      }}
                      onPointerUp={() => voice.capture.finish()}
                      onPointerCancel={() => voice.capture.cancel()}
                    >
                      <Mic size={16} /> {voice.phase === "recording" ? "Listening…" : "Hold to talk · R1"}
                    </button>
                    {!voice.active && <small role="status">{voice.message}</small>}
                  </div>
                )}
                <form className="row" onSubmit={send}>
                  <input aria-label="HumanCLI instruction" value={chat} onChange={(e) => setChat(e.target.value)} placeholder="Tell the robot what to do" />
                  <button className="primary" disabled={!chat.trim() || state.agent.busy || !!busy || state.agent.model?.configured === false}>
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
            disabled={!!busy || (!state.session && (!online || !canRecord || !space))}
            title={canRecord ? undefined : "Recording needs ConsoleBridge in the blueprint"}
            onClick={() => void run("record", () => api(state.session ? "/record/stop" : "/record/start", { space_id: spaceId }))}
          >
            {state.session ? "Save recording" : "Record"}
          </button>
        </section>
      </div>

      <Archive state={state} spaceId={spaceId} notify={notify} beforeMap={pauseControl} />

      <section className="card robot-actions" aria-label="Robot actions">
        {kind === "vector" ? (
          <>
            <VectorSensors data={state.telemetry.vector} connected={online} />
            <h2>Native personality</h2>
            <p className="muted">
              {state.telemetry.control?.ownership === "native"
                ? "Native personality active"
                : state.telemetry.control?.ownership === "stopped"
                  ? "Stopped"
                  : state.telemetry.control?.ownership === "app"
                    ? "App has control"
                    : "Waiting for ownership status"}
              {" · "}Vector services: {state.vector_services?.state || "stopped"}. {state.vector_services?.message}
            </p>
            {state.telemetry.control?.action && (
              <p role="status">
                {state.telemetry.control.action.name}: {state.telemetry.control.action.status}
                {state.telemetry.control.action.error ? ` · ${state.telemetry.control.action.error}` : ""}
                {state.telemetry.control.action.result?.message ? ` · ${state.telemetry.control.action.result.message}` : ""}
              </p>
            )}
            <div className="row">
              <button
                disabled={!online || !!busy || state.mode !== "idle" || estop}
                onClick={() => void run("personality", () => api("/vector/personality"))}
              >
                Resume native personality
              </button>
            </div>
          </>
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
              <UnitreeActions connected={online} mode={state.mode} stopped={estop} epoch={state.epoch} enabled={enabled("teleop")} api={api} />
            )}
          </>
        )}
        <details>
          <summary>Diagnostics</summary>
          <ul className="list">
            <li>
              Motion: {state.telemetry.motion?.sent ?? 0} commands sent
              {state.telemetry.motion?.observed_speed !== undefined &&
                ` · observed ${state.telemetry.motion.observed_speed.toFixed(2)} m/s, ${(state.telemetry.motion.observed_yaw_rate ?? 0).toFixed(2)} rad/s`}
            </li>
            <li>
              Planner commands received {state.telemetry.control?.nav_received ?? 0} · forwarded {state.telemetry.control?.nav_forwarded ?? 0}
            </li>
            {state.telemetry.motion?.error && <li className="error-text">{state.telemetry.motion.error}</li>}
            {state.segment && (
              <li>
                Recording to <code>{state.segment.path}</code>
                <button aria-label="Copy recording path" onClick={() => void copy(state.segment!.path)}>
                  <Copy size={13} />
                </button>
                · {state.telemetry.recording?.dropped || 0} dropped messages
              </li>
            )}
            <li>Modules: {(state.modules || []).join(", ")}</li>
          </ul>
        </details>
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
            {busy === "end" ? "Ending session…" : "End session"}
          </button>
          <button onClick={() => setEnding(false)}>Keep going</button>
        </Dialog>
      )}
    </main>
  );
}
