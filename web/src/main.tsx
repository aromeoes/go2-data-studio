import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  Camera,
  Check,
  ChevronRight,
  Circle,
  Compass,
  Copy,
  Download,
  Folder,
  Layers,
  Map,
  Pause,
  Pencil,
  Trash2,
  Play,
  Plus,
  Radio,
  ScanLine,
  Send,
  Square,
  Terminal,
  Wifi,
  X,
} from "lucide-react";
import "./style.css";
import { robot } from "./sdk";

import type { Item, State } from "./types";
import { MapCanvas } from "./MapCanvas";
import { HumanCLISettings } from "./HumanCLISettings";
import { HumanCLIHelp } from "./HumanCLIHelp";
import { TeleopPad } from "./TeleopPad";
import { CloudPanel, BackupControl } from "./Cloud";
import { BatteryStatus, NavigationPanel } from "./RobotStatus";
const gb = (n = 0) =>
  (n / 1e9).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const date = (n: number) =>
  new Date(n * 1000).toLocaleString("en-US", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
const labels: Record<string, string> = {
  offline: "Go2 disconnected",
  connecting: "Starting DimOS",
  reconnecting: "Looking for Go2",
  online: "Go2 connected",
  recording: "Recording",
  closed: "Saved",
  interrupted: "Interrupted",
  queued: "Queued",
  running: "Generating",
  ready: "Ready",
  failed: "Error",
  cancelled: "Cancelled",
  idle: "Paused",
  teleop: "Teleop",
  explore: "Exploration",
  agent: "HumanCLI",
};
async function api(path: string, data: unknown = {}) {
  if (
    [
      "/mode",
      "/heartbeat",
      "/release",
      "/stop",
      "/clear",
      "/agent",
      "/posture/stand",
      "/posture/lie",
    ].includes(path)
  )
    return robot.command(path, data);
  const r = await fetch("/api" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Go2-Request": "1" },
    body: JSON.stringify(data),
  });
  const value = await r.json();
  if (!r.ok)
    throw Error(
      typeof value.detail === "string"
        ? value.detail
        : "Could not complete the action",
    );
  return value;
}

export function App() {
  const [state, setState] = useState<State | null>(null);
  const [selected, setSelected] = useState("");
  const [ip, setIp] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState("");
  const [modal, setModal] = useState<"space" | "rename" | "import" | null>(
    null,
  );
  const [deleteSegment, setDeleteSegment] = useState<Item | null>(null);
  const [renameId, setRenameId] = useState("");
  const [input, setInput] = useState("");
  const [chat, setChat] = useState("");
  const [controlView, setControlView] = useState<string | null>(null);
  const [disconnectDialog, setDisconnectDialog] = useState(false);
  const [parked, setParked] = useState(false);
  const [armed, setArmed] = useState(false);
  const [teleopSpeed, setTeleopSpeed] = useState(0.5);
  const [pressed, setPressed] = useState<string[]>([]);
  const emitTeleop = useRef<(() => void) | null>(null);
  const [tab, setTab] = useState<"sessions" | "maps" | "events">("sessions");
  const [resolution, setResolution] = useState(0.1);
  const [pgo, setPgo] = useState(true);
  const [, setTick] = useState(0);
  const [online, setOnline] = useState(true);
  const [quality, setQuality] = useState<Item | null>(null);
  const keys = useRef(new Set<string>());
  const stateRef = useRef<State | null>(null);
  const heldEpoch = useRef<number | null>(null);
  const refresh = async () => {
    try {
      let value = robot.current();
      if (!value) {
        const r = await fetch("/api/state");
        if (!r.ok) throw Error();
        value = (await r.json()) as State;
        // HTTP remains for disconnected setup and the file catalog.
        value.telemetry = {};
      }
      if (
        value.mode === "idle" &&
        heldEpoch.current !== null &&
        value.epoch >= heldEpoch.current
      )
        heldEpoch.current = null;
      setState(value);
      stateRef.current = value;
      setOnline(true);
      if (
        value.mode !== "teleop" &&
        (heldEpoch.current === null || value.epoch >= heldEpoch.current)
      ) {
        setArmed(false);
        keys.current.clear();
        setPressed([]);
      }
      setSelected((v) => v || value.spaces[0]?.id || "");
      setIp((v) => (value.connection === "offline" ? v || value.ip : value.ip));
      setTick((v) => v + 1);
    } catch {
      setOnline(false);
      setArmed(false);
      keys.current.clear();
      setPressed([]);
    }
  };
  useEffect(() => {
    robot.onChange = () => {
      void refresh();
    };
    robot.onArmed = setArmed;
    void robot.start().catch((e) => setError(e.message));
    refresh();
    const id = setInterval(refresh, 1000);
    return () => {
      clearInterval(id);
      robot.close();
    };
  }, []);
  const action = async (name: string, fn: () => Promise<unknown>) => {
    setPending(name);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending("");
    }
  };
  const halt = () => {
    robot.machine?.estop();
    robot.disarm();
    heldEpoch.current = null;
    setArmed(false);
    keys.current.clear();
    setPressed([]);
    void action("stop", () => api("/stop"));
  };
  const mode = async (next: string) => {
    if (next !== "idle") setControlView(next);
    robot.disarm();
    setArmed(false);
    keys.current.clear();
    setPressed([]);
    heldEpoch.current = null;
    await action("mode", async () => {
      const result = await api("/mode", { mode: next });
      heldEpoch.current = result.epoch;
    });
  };
  const posture = async (next: "stand" | "lie") => {
    robot.disarm();
    heldEpoch.current = null;
    setArmed(false);
    keys.current.clear();
    setPressed([]);
    await action(next, async () => {
      const result = await api(`/posture/${next}`);
      if (!result.ok)
        throw new Error("Go2 did not confirm the posture change.");
    });
  };
  const toggleKeyboard = async () => {
    const previous = heldEpoch.current;
    heldEpoch.current = null;
    keys.current.clear();
    setPressed([]);
    if (armed) {
      robot.disarm();
      setArmed(false);
      if (previous !== null)
        await action("keyboard", () => api("/release", { epoch: previous }));
      return;
    }
    // A visible Teleop panel can outlive its lease after blur or a lost heartbeat.
    // Always acquire a fresh epoch rather than arming a keyboard that sends nothing.
    await action("keyboard", async () => {
      const result = await api("/mode", { mode: "teleop" });
      if (document.hidden || !document.hasFocus()) {
        await api("/release", { epoch: result.epoch });
        throw new Error("Return to the console and enable the controls again.");
      }
      heldEpoch.current = result.epoch;
      robot.arm(teleopSpeed);
    });
  };
  useEffect(() => {
    const timer = setInterval(() => {
      const s = stateRef.current;
      const epoch = heldEpoch.current;
      if (!s || epoch === null || !online) return;
      if (document.hidden) {
        heldEpoch.current = null;
        setArmed(false);
        keys.current.clear();
        setPressed([]);
        void api("/release", { epoch }).catch(() => {});
        return;
      }
      void api("/heartbeat", { epoch })
        .then((result) => {
          if (!result.ok && heldEpoch.current === epoch) {
            heldEpoch.current = null;
            setArmed(false);
          }
        })
        .catch(() => {
          if (heldEpoch.current !== epoch) return;
          heldEpoch.current = null;
          setArmed(false);
        });
    }, 250);
    return () => clearInterval(timer);
  }, [online]);
  useEffect(() => {
    if (!armed) return;
    const armedEpoch = heldEpoch.current;
    const keyOf = (e: KeyboardEvent) =>
      e.code.startsWith("Key") ? e.code.slice(3).toLowerCase() : e.key;
    const down = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        e.target.matches("input,textarea,select,[contenteditable=true]")
      ) {
        blur();
        return;
      }
      if (
        [
          "w",
          "a",
          "s",
          "d",
          "q",
          "e",
          "ArrowUp",
          "ArrowDown",
          "ArrowLeft",
          "ArrowRight",
        ].includes(keyOf(e))
      ) {
        e.preventDefault();
        if (!keys.current.has(keyOf(e))) {
          keys.current.add(keyOf(e));
          setPressed([...keys.current]);
          emitTeleop.current?.();
        }
      }
      if (e.code === "Space" || e.code === "Escape") {
        e.preventDefault();
        halt();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (keys.current.delete(keyOf(e))) {
        setPressed([...keys.current]);
        emitTeleop.current?.();
      }
    };
    const blur = () => {
      // An old Teleop blur must never release a newer HumanCLI lease.
      if (heldEpoch.current !== armedEpoch) return;
      robot.disarm();
      keys.current.clear();
      setPressed([]);
      setArmed(false);
      heldEpoch.current = null;
      if (armedEpoch !== null)
        void api("/release", { epoch: armedEpoch }).catch(() => {});
    };
    const outside = (event: Event) => {
      if (
        event.target instanceof HTMLElement &&
        !event.target.closest(".teleop")
      )
        blur();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    window.addEventListener("pointerdown", outside);
    window.addEventListener("focusin", outside);
    emitTeleop.current = () => robot.keys(keys.current);
    return () => {
      robot.disarm();
      emitTeleop.current = null;
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      window.removeEventListener("pointerdown", outside);
      window.removeEventListener("focusin", outside);
      keys.current.clear();
      setPressed([]);
    };
  }, [armed, teleopSpeed]);
  const copy = async (path: string) => {
    await navigator.clipboard.writeText(path);
    setNotice("Path copied");
    setTimeout(() => setNotice(""), 2000);
  };
  if (!state)
    return (
      <div className="loading">
        <ScanLine size={30} />
        <h1>Space setup</h1>
        <p>
          {online
            ? "Loading the local console…"
            : "The app is not responding. Open Iniciar Go2.command."}
        </p>
      </div>
    );
  const shownControl =
    controlView ?? (state.mode === "idle" ? "teleop" : state.mode);
  const space = state.spaces.find((s) => s.id === selected);
  const sessions = state.sessions.filter((s) => s.parent === selected);
  const segments = state.segments.filter((s) =>
    sessions.some((x) => x.id === s.parent),
  );
  const maps = state.maps.filter((m) =>
    segments.some((s) => s.id === m.parent),
  );
  const stats = state.stats;
  const connected =
    state.connection === "online" && online && !!robot.current();
  const sensor = state.telemetry.sensors || {};
  const hasCamera =
    !!robot.camera &&
    !!sensor.color_image &&
    Date.now() / 1000 - sensor.color_image.received < 4;
  const open = (id: string, kind: string) =>
    void action("open", () => api(`/open/${id}/${kind}`));
  return (
    <div className="app">
      <aside className="rail">
        <div className="brand">
          <div className="brandmark">
            D<span>↗</span>
          </div>
          <div>
            DIMENSIONAL<small>ROBOT WORKSPACE</small>
          </div>
        </div>
        <div className="rail-title">
          SPACES
          <button
            aria-label="Create space"
            onClick={() => {
              setInput("");
              setModal("space");
            }}
          >
            <Plus size={16} />
          </button>
        </div>
        <nav>
          {state.spaces.map((s) => (
            <button
              key={s.id}
              className={"space " + (selected === s.id ? "selected" : "")}
              onClick={() => setSelected(s.id)}
            >
              <Map size={17} />
              <span>{s.name}</span>
              <ChevronRight size={14} />
            </button>
          ))}
          {!state.spaces.length && (
            <p className="muted rail-empty">
              Create your first space to organize its recordings and maps.
            </p>
          )}
        </nav>
        <button
          className="new-space"
          onClick={() => {
            setInput("");
            setModal("space");
          }}
        >
          <Plus size={15} />
          New space
        </button>
        <CloudPanel
          cloud={state.cloud}
          action={action}
          api={api}
          pending={!!pending}
        />
        <div className="rail-bottom">
          <span className="eyebrow">LOCAL STORAGE</span>
          <strong>
            {gb(state.disk_free)} <small>GB free</small>
          </strong>
          <div className="disk-line" />
          <span className="storage-path" title={state.storage_root}>
            {state.storage_root}
          </span>
          <p>
            Original recordings
            <br />
            stay on this Mac.
          </p>
          <div className="version">
            DimOS 0.0.14 <span>{state.dimos_sha.slice(0, 7)}</span>
          </div>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Go2 <ChevronRight size={13} /> <span>Space setup</span>
          </div>
          <div className="top-right">
            <BatteryStatus state={state} connected={connected} />
            <span className={"status " + (connected ? "good" : "")}>
              <i />
              {!online
                ? "Console offline"
                : state.replay
                  ? "REPLAY · recording"
                  : labels[state.connection]}
            </span>
            <button className="stop" onClick={halt}>
              <Square size={13} fill="currentColor" />
              Stop
            </button>
          </div>
        </header>
        <section className="heading">
          <div>
            <div className="eyebrow">
              SPACE SETUP <span>PHASE 01</span>
            </div>
            <h1>
              {space?.name || "A new space to explore"}
              <span className="title-dot">.</span>
              {space && (
                <button
                  className="rename-space"
                  aria-label="Rename space"
                  title="Rename space"
                  disabled={!!pending}
                  onClick={() => {
                    setRenameId(space.id);
                    setInput(space.name || "");
                    setError("");
                    setModal("rename");
                  }}
                >
                  <Pencil size={17} />
                </button>
              )}
            </h1>
            <p>Explore, record, and map your space.</p>
          </div>
          <div className="connect">
            <label htmlFor="robot-ip">GO2 IP ADDRESS</label>
            <div>
              <input
                id="robot-ip"
                value={ip}
                onChange={(e) => setIp(e.target.value)}
                placeholder="192.168.1.20"
                disabled={state.connection !== "offline"}
              />
              <button
                className="primary"
                disabled={!!pending}
                onClick={() => {
                  if (state.connection === "offline") {
                    void action("connect", () => api("/connect", { ip }));
                  } else if (state.replay) {
                    void action("disconnect", () => api("/disconnect"));
                  } else {
                    setParked(false);
                    setDisconnectDialog(true);
                    if (connected) void mode("idle");
                  }
                }}
              >
                <Wifi size={15} />
                {state.connection === "offline" ? "Connect" : "Disconnect"}
              </button>
            </div>
          </div>
        </section>
        {(error || state.error || !online) && (
          <div className="alert" role="alert">
            <span>
              {error ||
                state.error ||
                "The console lost connection. Motion control expires automatically."}
            </span>
            {error && (
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            )}
          </div>
        )}
        {state.replay && (
          <div className="replay-note">
            <Play size={14} />
            Playing recorded data. Controls do not move a physical robot.
          </div>
        )}
        <div className="workspace">
          <section className="map-panel panel">
            <div className="panel-head">
              <div>
                <Map size={16} />
                <strong>Space map</strong>
                <span className="tiny-pill">2D · OCCUPANCY</span>
              </div>
              <span className="mono">
                {state.telemetry.map
                  ? state.telemetry.map.known_m2.toFixed(1) + " m² observed"
                  : "No data yet"}
              </span>
            </div>
            <MapCanvas
              grid={state.telemetry.map}
              pose={state.telemetry.pose}
              path={state.telemetry.path}
            />
            <div className="map-footer">
              <span>
                <i className={connected ? "live-dot" : "offline-dot"} />
                {state.telemetry.map
                  ? "Preview map · updated by LiDAR"
                  : "Waiting for sensors"}
              </span>
              <span className="mono">
                {state.telemetry.pose
                  ? `X ${state.telemetry.pose.x.toFixed(2)}  Y ${state.telemetry.pose.y.toFixed(2)} m`
                  : "X · · ·   Y · · ·"}
              </span>
            </div>
          </section>
          <aside className="control-panel">
            <section className="camera panel">
              <div className="panel-head">
                <div>
                  <Camera size={16} />
                  <strong>Front camera</strong>
                </div>
                <span className="mono">{hasCamera ? "RGB" : "NO SIGNAL"}</span>
              </div>
              <div className="camera-feed">
                {hasCamera ? (
                  <img src={robot.camera || undefined} alt="Go2 front camera" />
                ) : (
                  <>
                    <Camera size={28} />
                    <span>Camera feed appears when connected</span>
                  </>
                )}
              </div>
            </section>
            {!robot.current() && state.connection === "online" && (
              <p role="status">
                {robot.error || "Connecting to DimOS Web SDK…"}
              </p>
            )}
            <div className="sensor-health">
              {[
                ["lidar", "LiDAR"],
                ["odom", "Position"],
                ["color_image", "Camera"],
              ].map(([key, label]) => (
                <span key={key}>
                  <i
                    className={
                      sensor[key] &&
                      Date.now() / 1000 - sensor[key].received < 2
                        ? "live-dot"
                        : "offline-dot"
                    }
                  />
                  {label}
                </span>
              ))}
            </div>
            <section className="controls panel">
              <div className="panel-head">
                <div>
                  <Compass size={16} />
                  <strong>Go2 controls</strong>
                </div>
                <span className="tiny-pill">{labels[state.mode]}</span>
              </div>
              <div className="mode-switch">
                {[
                  ["teleop", "Teleop"],
                  ["explore", "Explore"],
                  ["agent", "HumanCLI"],
                ].map(([m, l]) => (
                  <button
                    key={m}
                    disabled={!connected || !!pending}
                    className={shownControl === m ? "active" : ""}
                    onClick={() => mode(m)}
                  >
                    {m === "teleop" ? (
                      <Radio size={16} />
                    ) : m === "explore" ? (
                      <Compass size={16} />
                    ) : (
                      <Terminal size={16} />
                    )}
                    {l}
                  </button>
                ))}
              </div>
              <NavigationPanel navigation={state.telemetry.navigation} />
              {!state.telemetry.navigation &&
                state.telemetry.control?.stop_reason && (
                  <p role="status">{state.telemetry.control.stop_reason}</p>
                )}
              {state.telemetry.motion && (
                <details className="motion-details">
                  <summary>Motion diagnostics</summary>
                  <div className="motion-status">
                    <small>
                      Transport: velocity commands · Sent:{" "}
                      {state.telemetry.motion.sent}
                    </small>
                    {state.telemetry.motion.observed_speed !== undefined && (
                      <small>
                        Observed motion:{" "}
                        {state.telemetry.motion.observed_speed.toFixed(2)} m/s ·
                        rotation{" "}
                        {(
                          state.telemetry.motion.observed_yaw_rate ?? 0
                        ).toFixed(2)}{" "}
                        rad/s
                      </small>
                    )}
                    {state.mode === "explore" && (
                      <small>
                        Planner commands received:{" "}
                        {state.telemetry.control?.nav_received ?? 0} ·
                        forwarded: {state.telemetry.control?.nav_forwarded ?? 0}
                      </small>
                    )}
                    {state.telemetry.motion.error && (
                      <p role="alert">{state.telemetry.motion.error}</p>
                    )}
                  </div>
                </details>
              )}
              {shownControl === "teleop" ? (
                <TeleopPad
                  speed={teleopSpeed}
                  setSpeed={setTeleopSpeed}
                  armed={armed}
                  disabled={
                    !connected || !!pending || !!state.telemetry.control?.estop
                  }
                  pressed={pressed}
                  toggle={() => void toggleKeyboard()}
                  press={(key) => {
                    if (!armed) return;
                    keys.current.add(key);
                    setPressed([...keys.current]);
                    emitTeleop.current?.();
                  }}
                  release={(key) => {
                    if (keys.current.delete(key)) {
                      setPressed([...keys.current]);
                      emitTeleop.current?.();
                    }
                  }}
                />
              ) : shownControl === "explore" ? (
                <div className="navigation-actions">
                  <button onClick={() => mode("idle")}>
                    <Pause size={14} />
                    Pause exploration
                  </button>
                </div>
              ) : shownControl === "agent" ? (
                <div className="humancli">
                  <div className="humancli-heading">
                    <strong>HumanCLI</strong>
                    <HumanCLIHelp
                      capabilities={state.agent.capabilities || []}
                    />
                    <button
                      className="new-conversation"
                      disabled={!!pending}
                      onClick={() =>
                        action("conversation", async () => {
                          await api("/agent/conversation");
                          setChat("");
                        })
                      }
                    >
                      New conversation
                    </button>
                  </div>
                  {state.mode !== "agent" && (
                    <div className="humancli-paused" role="status">
                      <p>
                        HumanCLI stays open while movement is paused. Enable it
                        to send a new instruction.
                      </p>
                      <button
                        disabled={
                          !connected ||
                          !!pending ||
                          !!state.telemetry.control?.estop
                        }
                        onClick={() => mode("agent")}
                      >
                        Enable HumanCLI
                      </button>
                    </div>
                  )}
                  <p>
                    DimOS agent ·{" "}
                    {state.agent.model?.configured
                      ? `${state.agent.model.provider} / ${state.agent.model.model}`
                      : "Configure a model below to begin."}{" "}
                    Movement stays within mapped clear space. Camera access is
                    optional.
                  </p>
                  <HumanCLISettings
                    config={state.agent.model}
                    pending={!!pending || state.agent.busy}
                    save={async (value) => {
                      setPending("agent-config");
                      try {
                        await api("/agent/config", value);
                        await refresh();
                      } finally {
                        setPending("");
                      }
                    }}
                  />
                  {state.agent.busy && (
                    <div className="agent-progress" role="status">
                      <span>HumanCLI is working…</span>
                      <button
                        onClick={() =>
                          action("agent-cancel", () => api("/agent/cancel"))
                        }
                      >
                        Cancel response
                      </button>
                    </div>
                  )}
                  <div className="messages">
                    {!state.agent.messages.filter(
                      (m) => Date.now() / 1000 - m.ts < 1800,
                    ).length ? (
                      <span className="muted">
                        Try “walk one meter backward” or “what do you see?”.
                      </span>
                    ) : (
                      state.agent.messages
                        .filter((m) => Date.now() / 1000 - m.ts < 1800)
                        .slice(-10)
                        .map((m, i) => (
                          <div key={i} className={"message " + m.role}>
                            <small>
                              {m.role === "user"
                                ? "YOU"
                                : m.role === "tool"
                                  ? "TOOL"
                                  : "HUMANCLI"}
                            </small>
                            {m.text}
                          </div>
                        ))
                    )}
                  </div>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void action("agent", async () => {
                        if (
                          stateRef.current?.mode !== "agent" ||
                          heldEpoch.current === null
                        )
                          throw Error(
                            "Enable HumanCLI before sending an instruction.",
                          );
                        await api("/agent", {
                          text: chat,
                          epoch: heldEpoch.current,
                          space_id: selected || null,
                        });
                        setChat("");
                      });
                    }}
                  >
                    <input
                      aria-label="HumanCLI instruction"
                      value={chat}
                      onChange={(e) => setChat(e.target.value)}
                      placeholder="Go to the far end…"
                    />
                    <button
                      aria-label="Send instruction"
                      disabled={
                        !chat.trim() ||
                        !!pending ||
                        state.mode !== "agent" ||
                        state.agent.busy ||
                        state.agent.model?.configured === false
                      }
                    >
                      <Send size={16} />
                    </button>
                  </form>
                </div>
              ) : (
                <div className="mode-info">
                  <Radio size={28} />
                  <h3>Ready to take control</h3>
                  <p>
                    Connect Go2 and choose how to explore. Recording works in
                    every control mode.
                  </p>
                </div>
              )}
              {state.telemetry.control?.estop && (
                <button
                  className="clear-stop"
                  onClick={() => action("clear", () => api("/clear"))}
                >
                  Release stop to select a mode
                </button>
              )}
              <div className="posture">
                <button
                  disabled={!connected || !!pending}
                  onClick={() => void posture("stand")}
                >
                  Stand up
                </button>
                <button
                  disabled={!connected || !!pending}
                  onClick={() => void posture("lie")}
                >
                  Lie down
                </button>
              </div>
            </section>
          </aside>
        </div>
        <section
          className={
            "record-bar panel " + (state.session ? "is-recording" : "")
          }
        >
          <div className="record-title">
            <div className="record-icon">
              <Circle
                size={18}
                fill={state.session ? "currentColor" : "none"}
              />
            </div>
            <div>
              <strong>
                {state.session
                  ? `Recording · ${state.spaces.find((s) => s.id === state.session?.parent)?.name || "space"}`
                  : stats
                    ? "Last saved session"
                    : "Record your exploration"}
              </strong>
              <span>
                {state.session
                  ? state.segment
                    ? "LiDAR + camera + odometry + TF"
                    : "Waiting to reconnect and start another segment"
                  : "One session, every control mode"}
              </span>
            </div>
          </div>
          <div className="record-numbers">
            <div>
              <label>LIDAR</label>
              <strong>
                {gb(stats?.streams.lidar?.bytes)} <small>GB</small>
              </strong>
            </div>
            <div>
              <label>CAMERA</label>
              <strong>
                {gb(stats?.streams.color_image?.bytes)} <small>GB</small>
              </strong>
            </div>
            <div>
              <label>TOTAL ON DISK</label>
              <strong>
                {gb(stats?.physical_bytes)} <small>GB</small>
              </strong>
            </div>
            <div>
              <label>AVERAGE RATE</label>
              <strong>
                {(stats?.gb_per_min || 0).toFixed(2)} <small>GB/min</small>
              </strong>
            </div>
          </div>
          <button
            className={state.session ? "record-stop" : "primary"}
            disabled={
              !!pending || (!state.session && (!connected || !selected))
            }
            onClick={() =>
              action("record", () =>
                api(state.session ? "/record/stop" : "/record/start", {
                  space_id: selected,
                }),
              )
            }
          >
            {state.session ? <Square size={14} /> : <Circle size={14} />}{" "}
            {state.session ? "Save session" : "Record a session"}
          </button>
        </section>
        {state.segment && (
          <div className="live-path">
            <Folder size={13} />
            <code>{state.segment.path}</code>
            <button
              aria-label="Copy recording path"
              onClick={() => copy(state.segment!.path!)}
            >
              <Copy size={13} />
            </button>
            <span>
              {state.telemetry.recording?.dropped || 0} dropped messages
            </span>
          </div>
        )}
        <section className="archive">
          <div className="archive-head">
            <div className="tabs">
              <button
                className={tab === "sessions" ? "active" : ""}
                onClick={() => setTab("sessions")}
              >
                Recordings <span>{segments.length}</span>
              </button>
              <button
                className={tab === "maps" ? "active" : ""}
                onClick={() => setTab("maps")}
              >
                Generated maps <span>{maps.length}</span>
              </button>
              <button
                className={tab === "events" ? "active" : ""}
                onClick={() => setTab("events")}
              >
                Activity
              </button>
            </div>
            <button
              disabled={!selected}
              onClick={() => {
                setInput("");
                setModal("import");
              }}
            >
              <Plus size={14} />
              Import recording
            </button>
          </div>
          {tab === "sessions" &&
            (segments.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>SEGMENT / DATE</th>
                      <th>DATA</th>
                      <th>DURATION</th>
                      <th>STATUS</th>
                      <th>CLOUD BACKUP</th>
                      <th>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {segments.map((s, i) => (
                      <tr key={s.id}>
                        <td>
                          <strong>
                            <Layers size={14} />
                            Segment {segments.length - i}
                          </strong>
                          <small>
                            {date(s.created)} · {s.id.slice(0, 6)} ·{" "}
                            {sessions.find((session) => session.id === s.parent)
                              ?.source === "replay"
                              ? "REPLAY"
                              : sessions.find(
                                    (session) => session.id === s.parent,
                                  )?.source === "import"
                                ? "IMPORTED"
                                : "ROBOT"}
                          </small>
                          <code title={s.path}>{s.path}</code>
                        </td>
                        <td>
                          <span>{gb(s.stats?.physical_bytes)} GB</span>
                          <small>
                            {(
                              s.stats?.streams.lidar?.count || 0
                            ).toLocaleString()}{" "}
                            LiDAR clouds
                          </small>
                        </td>
                        <td className="mono">
                          {((s.stats?.duration || 0) / 60).toFixed(1)} min
                        </td>
                        <td>
                          <span className={"badge " + s.status}>
                            {labels[s.status] || s.status}
                          </span>
                        </td>
                        <td>
                          <BackupControl
                            segment={s}
                            cloud={state.cloud}
                            action={action}
                            api={api}
                            pending={!!pending}
                          />
                        </td>
                        <td>
                          <div className="row-actions">
                            <button
                              title="Show file in Finder"
                              aria-label="Show recording in Finder"
                              onClick={() => open(s.id, "raw")}
                            >
                              <Folder size={15} />
                            </button>
                            <button
                              title="Copy path"
                              aria-label="Copy path"
                              onClick={() => copy(s.path!)}
                            >
                              <Copy size={15} />
                            </button>
                            <button
                              disabled={
                                state.connection !== "offline" ||
                                s.status === "recording" ||
                                !!pending
                              }
                              onClick={() =>
                                action("replay", () =>
                                  api("/connect", { segment_id: s.id }),
                                )
                              }
                            >
                              <Play size={13} />
                              Replay
                            </button>
                            <button
                              disabled={
                                s.status === "recording" ||
                                !!pending ||
                                state.mode !== "idle"
                              }
                              onClick={() =>
                                action("map", async () => {
                                  await api("/maps", {
                                    segment_id: s.id,
                                    voxel: resolution,
                                    pgo,
                                  });
                                  setTab("maps");
                                })
                              }
                            >
                              Generate map
                              <ArrowUpRight size={14} />
                            </button>
                            {s.backup?.status !== "complete" && (
                              <button
                                aria-label={`Delete segment ${s.id.slice(0, 6)}`}
                                title="Delete local segment and its generated maps"
                                disabled={
                                  !!pending ||
                                  ["recording", "importing"].includes(
                                    s.status,
                                  ) ||
                                  state.session?.id === s.parent ||
                                  state.cloud?.active_segment === s.id ||
                                  [
                                    "preparing",
                                    "uploading",
                                    "verifying",
                                  ].includes(s.backup?.status || "") ||
                                  (state.replay &&
                                    state.connection !== "offline") ||
                                  state.maps.some(
                                    (m) =>
                                      m.parent === s.id &&
                                      ["queued", "running"].includes(m.status),
                                  )
                                }
                                onClick={() => {
                                  setError("");
                                  setDeleteSegment(s);
                                }}
                              >
                                <Trash2 size={15} />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="generation-options">
                  <label>
                    Resolution{" "}
                    <select
                      value={resolution}
                      onChange={(e) => setResolution(Number(e.target.value))}
                    >
                      <option value={0.1}>10 cm · fast</option>
                      <option value={0.05}>5 cm · detailed</option>
                    </select>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={pgo}
                      onChange={(e) => setPgo(e.target.checked)}
                    />
                    Optimize trajectory (PGO)
                  </label>
                  <span>Each generation creates a new version.</span>
                </div>
              </div>
            ) : (
              <div className="archive-empty">
                <Layers size={24} />
                <div>
                  <strong>No saved recordings yet</strong>
                  <p>Record a session or import a DimOS .db file.</p>
                </div>
              </div>
            ))}
          {tab === "maps" &&
            (maps.length ? (
              <div className="map-list">
                {maps.map((m, i) => (
                  <article className="map-version" key={m.id}>
                    <div className="map-file">
                      <Map size={24} />
                    </div>
                    <div className="map-version-info">
                      <strong>
                        Map {maps.length - i}
                        <span className={"badge " + m.status}>
                          {labels[m.status]}
                        </span>
                      </strong>
                      <p>
                        {date(m.created)} · {(m.voxel || 0.1) * 100} cm ·
                        PointCloud2 / Rerun
                      </p>
                      <code title={m.map_path || m.folder}>
                        {m.map_path || m.folder}
                      </code>
                      {m.error && <p className="error-text">{m.error}</p>}
                      {m.status === "running" && (
                        <div className="progress">
                          <i />
                        </div>
                      )}
                    </div>
                    <div className="row-actions">
                      <button
                        onClick={() => open(m.id, "folder")}
                        aria-label="Show map folder"
                      >
                        <Folder size={16} />
                      </button>
                      {m.log && (
                        <a href={`/api/files/${m.id}/log`} target="_blank">
                          Log
                        </a>
                      )}
                      {m.status === "ready" ? (
                        <>
                          <button onClick={() => setQuality(m)}>Quality</button>
                          <button
                            className="primary"
                            disabled={!m.rerun_path}
                            onClick={() => open(m.id, "rerun")}
                          >
                            Open in Rerun
                            <ArrowUpRight size={14} />
                          </button>
                          <a
                            aria-label="Download map"
                            href={`/api/files/${m.id}/map`}
                          >
                            <Download size={15} />
                          </a>
                        </>
                      ) : ["running", "queued"].includes(m.status) ? (
                        <button
                          onClick={() =>
                            action("cancel", () => api(`/maps/${m.id}/cancel`))
                          }
                        >
                          Cancel
                        </button>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="archive-empty">
                <Map size={24} />
                <div>
                  <strong>Next step: generate your map</strong>
                  <p>Choose Generate map on a saved recording.</p>
                </div>
              </div>
            ))}
          {tab === "events" && (
            <div className="events">
              {state.events.length ? (
                state.events.map((e) => (
                  <div key={e.id}>
                    <span className="mono">{date(e.ts)}</span>
                    <span>{e.message}</span>
                  </div>
                ))
              ) : (
                <p className="muted">Session activity will appear here.</p>
              )}
            </div>
          )}
        </section>
        <footer>
          <span>SPACE SETUP / DIMENSIONAL</span>
          <span>Preview map ≠ map validated for patrol</span>
          <span>LOCAL · MAC + WI-FI</span>
        </footer>
      </main>
      {notice && (
        <div className="toast" role="status">
          <Check size={16} />
          {notice}
        </div>
      )}
      {pending && (
        <div className="pending" role="status">
          Processing…
        </div>
      )}
      {disconnectDialog && (
        <div className="overlay">
          <section
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Disconnect Go2"
          >
            <h2>Lie down before disconnecting</h2>
            <p>
              Wait until Go2 lies down and visually confirm it is supported. A
              sent command does not confirm posture.
            </p>
            <button
              disabled={!!pending || !connected}
              onClick={() => void action("lie", () => api("/posture/lie"))}
            >
              1. Lie down Go2
            </button>
            {!connected && (
              <p>
                No connection is available to request posture. Check the robot
                in person before closing the session.
              </p>
            )}
            <label>
              <input
                type="checkbox"
                checked={parked}
                onChange={(e) => setParked(e.target.checked)}
              />{" "}
              I confirm Go2 is lying down and supported
            </label>
            <button
              disabled={!parked || !!pending || state.mode !== "idle"}
              onClick={() =>
                void action("disconnect", async () => {
                  await api("/disconnect", { parked_confirmed: true });
                  setDisconnectDialog(false);
                  setParked(false);
                })
              }
            >
              2. Close connection
            </button>
            <button onClick={() => setDisconnectDialog(false)}>
              Back to dashboard
            </button>
          </section>
        </div>
      )}
      {deleteSegment && (
        <div
          className="overlay"
          onClick={() => !pending && setDeleteSegment(null)}
        >
          <section
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-title"
            aria-describedby="delete-detail"
            className="dialog"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !pending) setDeleteSegment(null);
            }}
          >
            <div className="eyebrow">LOCAL RECORDING</div>
            <h2 id="delete-title">
              Delete segment {deleteSegment.id.slice(0, 6)}?
            </h2>
            <p id="delete-detail">
              This segment has no confirmed backup of its current data.
              Permanently delete the local recording and{" "}
              {state.maps.filter((m) => m.parent === deleteSegment.id).length}{" "}
              generated maps? This cannot be undone. Existing cloud data and
              imported source files are kept.
            </p>
            <code className="delete-path">
              {deleteSegment.path || deleteSegment.folder}
            </code>
            {error && (
              <p className="error-text" role="alert">
                {error}
              </p>
            )}
            <button
              autoFocus
              disabled={!!pending}
              onClick={() => setDeleteSegment(null)}
            >
              Cancel
            </button>
            <button
              className="danger"
              disabled={!!pending}
              onClick={() =>
                void action("delete-segment", async () => {
                  const result = await api(
                    `/segments/${deleteSegment.id}/delete`,
                    { confirmed: true },
                  );
                  setNotice(
                    result.warning ||
                      "Local segment and generated maps deleted.",
                  );
                  setDeleteSegment(null);
                })
              }
            >
              {pending === "delete-segment"
                ? "Deleting…"
                : "Delete permanently"}
            </button>
          </section>
        </div>
      )}
      {modal && (
        <div className="overlay" onClick={() => !pending && setModal(null)}>
          <form
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "rename"
                ? "Rename space"
                : modal === "space"
                  ? "Create space"
                  : "Import recording"
            }
            className="dialog"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              void action(modal, async () => {
                if (modal === "space") {
                  const value = await api("/spaces", { name: input });
                  setSelected(value.id);
                } else if (modal === "rename") {
                  await api(`/spaces/${renameId}/rename`, { name: input });
                } else
                  await api("/import", { space_id: selected, path: input });
                setModal(null);
              });
            }}
          >
            <button
              className="dialog-close"
              type="button"
              aria-label="Close"
              onClick={() => setModal(null)}
            >
              <X size={18} />
            </button>
            <div className="eyebrow">
              {modal !== "import" ? "YOUR LIBRARY" : "EXISTING DATA"}
            </div>
            <h2>
              {modal === "rename"
                ? "Rename space"
                : modal === "space"
                  ? "Name this space"
                  : "Import a recording"}
            </h2>
            <p>
              {modal === "rename"
                ? "Recordings, maps, backups, and file paths stay linked to this space."
                : modal === "space"
                  ? "Its recordings and map versions will be stored together."
                  : "Enter the absolute path to the .db file. An independent copy will be saved; the original is preserved."}
            </p>
            <label>
              {modal !== "import" ? "Space name" : "Path to the .db file"}
              <input
                autoFocus
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={
                  modal !== "import"
                    ? "e.g. Buenos Aires office"
                    : "/path/to/recording.db"
                }
                maxLength={modal !== "import" ? 80 : 2000}
              />
            </label>
            {error && <p className="error-text">{error}</p>}
            <button className="primary" disabled={!input.trim() || !!pending}>
              {pending
                ? "Processing…"
                : modal === "rename"
                  ? "Save name"
                  : modal === "space"
                    ? "Create space"
                    : "Import copy"}
            </button>
          </form>
        </div>
      )}
      {quality && (
        <div className="overlay" onClick={() => setQuality(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Map quality"
            className="dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="dialog-close"
              aria-label="Close quality"
              onClick={() => setQuality(null)}
            >
              <X size={18} />
            </button>
            <div className="eyebrow">RECORDING EVIDENCE</div>
            <h2>Map quality</h2>
            <dl>
              <dt>LiDAR clouds</dt>
              <dd>{quality.quality?.lidar_frames.toLocaleString()}</dd>
              <dt>Clouds with pose</dt>
              <dd>
                {quality.quality?.lidar_pose_fraction != null
                  ? (quality.quality.lidar_pose_fraction * 100).toFixed(1) + "%"
                  : "No data"}
              </dd>
              <dt>Gaps longer than 1 s</dt>
              <dd>{quality.quality?.lidar_gaps_over_1s}</dd>
              <dt>Total space coverage</dt>
              <dd>No reference</dd>
              <dt>Absolute accuracy</dt>
              <dd>Not measured</dd>
            </dl>
            <p>
              These indicators describe the source data. Inspect geometry in
              Rerun before using the map for navigation. Segments from separate
              restarts require alignment.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
