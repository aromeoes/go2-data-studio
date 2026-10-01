/**
 * Start Session: choose a blueprint and its modules while the robot connects in
 * the background with only the required modules. START adds the rest to that
 * same connection.
 */
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Lock } from "lucide-react";
import { robot } from "../sdk";
import type { State } from "../types";
import { capabilitiesOf, embodiment, toggleModule, type ModuleDef } from "./modules";
import { api, cameraLive, gb, RobotPicture, robotLabel, Spinner, useElapsed, useStreamRate, type Notify } from "./ui";

export function StartSession({
  state,
  robotName,
  notify,
  onStarted,
  onBack,
}: {
  state: State;
  robotName: string;
  notify: Notify;
  onStarted: () => void;
  onBack: () => void;
}) {
  const kind = state.robot_kind || "go2";
  const { modules, blueprints } = embodiment(kind);
  const [blueprint, setBlueprint] = useState(blueprints[0].id);
  const [custom, setCustom] = useState(blueprints[0].modules);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState("");
  const sent = useRef(false);
  const failed = useRef(false);
  const locked = blueprints.find((b) => b.id === blueprint)!.locked;
  const available = new Set(modules.filter((m) => !m.unavailable).map((m) => m.id));
  const selected = (locked ? blueprints.find((b) => b.id === blueprint)!.modules : custom).filter((id) => available.has(id));
  const online = state.connection === "online";
  const connecting = state.connection === "connecting";
  const elapsed = useElapsed(!online);
  const rate = useStreamRate();
  const live = cameraLive(state);

  // START before the robot is online waits for it, then adds the modules.
  useEffect(() => {
    if (!starting || !online || sent.current) return;
    sent.current = true;
    api("/session/modules", {
      robot_id: state.robot_id ?? null,
      preset: blueprint,
      modules: selected,
      enabled: capabilitiesOf(selected, modules),
    }).catch((e) => {
      sent.current = false;
      setStarting(false);
      notify(e.message, "error");
    });
  }, [starting, online]);

  useEffect(() => {
    if (sent.current && online && state.profile?.preset !== "base" && !state.loading_modules) onStarted();
  }, [state]);

  // A robot that never answers: say so, close the attempt and go back to the robot list.
  useEffect(() => {
    if (state.connection !== "reconnecting" || failed.current) return;
    failed.current = true;
    notify(`Could not reach ${robotName} at ${state.ip}. Check that it is on and on the same Wi-Fi as this device.`, "error");
    void api("/disconnect").finally(onBack);
  }, [state.connection]);

  const toggle = (m: ModuleDef, on: boolean) => {
    const next = toggleModule(custom, m.id, on, modules);
    const changed = next.filter((id) => !custom.includes(id) && id !== m.id);
    const dropped = custom.filter((id) => !next.includes(id) && id !== m.id);
    setNotice(changed.length ? `Also added: ${changed.join(", ")}` : dropped.length ? `Also removed: ${dropped.join(", ")}` : "");
    setCustom(next);
  };

  return (
    <main className="screen">
      <header className="bar">
        <button
          className="link"
          disabled={starting}
          onClick={() => {
            void api("/disconnect").finally(onBack);
          }}
        >
          <ArrowLeft size={16} /> Robots
        </button>
        <span className="wordmark small">DIMENSIONAL</span>
        <span className="muted">Local storage: {gb(state.disk_free)} GB free</span>
      </header>
      <div className="setup">
        <section className="card setup-main">
          <h1>Select blueprint</h1>
          <div className="segmented" role="radiogroup" aria-label="Blueprint">
            {blueprints.map((b) => (
              <button key={b.id} role="radio" aria-checked={blueprint === b.id} disabled={starting} onClick={() => setBlueprint(b.id)}>
                <strong>
                  {b.name}
                  {b.recommended && <span className="tag">Recommended</span>}
                </strong>
                <small>{b.summary}</small>
              </button>
            ))}
          </div>
          <div className="row">
            <h2>Modules</h2>
            <span className="muted">
              {selected.length} selected{locked ? " · fixed in this blueprint" : ""}
            </span>
            <button disabled title="Coming soon">
              Install community module
            </button>
            <span className="tag">Coming soon</span>
          </div>
          {notice && !locked && <p className="hint" role="status">{notice}</p>}
          {(
            [
              ["DimOS modules", modules.filter((m) => m.official)],
              ["App modules", modules.filter((m) => !m.official)],
            ] as const
          ).map(([title, group]) => (
            <section key={title} className="module-group" aria-label={title}>
              <h3>{title}</h3>
              <ul className="modules">
                {[...group.filter((m) => !m.unavailable), ...group.filter((m) => m.unavailable)].map((m) => (
                  <li key={m.id} className={m.unavailable ? "unavailable" : ""} data-tip={m.summary}>
                    <label>
                      <input
                        type="checkbox"
                        checked={selected.includes(m.id)}
                        disabled={starting || locked || !!m.required || !!m.unavailable}
                        onChange={(e) => toggle(m, e.target.checked)}
                      />
                      <span className="module-icons">
                        {m.icons.map((Icon, i) => (
                          <Icon key={i} size={16} aria-hidden="true" />
                        ))}
                      </span>
                      <code>{m.id}</code>
                      {m.required && <Lock size={13} aria-label="Required" />}
                      {m.unavailable && <small>{m.unavailable}</small>}
                    </label>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </section>
        <aside className="card setup-side">
          <div className="preview">
            {live ? (
              <>
                <img src={robot.camera} alt={`${robotName} camera`} />
                <span className="live-badge">
                  ● LIVE · {rate.fps} fps · {rate.kbps} kB/s
                </span>
              </>
            ) : (
              <RobotPicture kind={kind} large />
            )}
          </div>
          <strong>{robotName}</strong>
          <span className="muted">
            {robotLabel(kind)} · {state.ip}
          </span>
          <p className="status-line">
            {online ? (
              <>
                <Check size={16} /> Connected. Camera is live.
              </>
            ) : (
              <Spinner>
                {connecting ? "Connecting" : "Reconnecting"} · {elapsed} s
              </Spinner>
            )}
          </p>
          <button className="primary start" disabled={starting} onClick={() => setStarting(true)}>
            START
          </button>
          <p className="hint">Starts once. The robot stays connected while you choose.</p>
        </aside>
      </div>
      {starting && (
        <div className="overlay">
          <section className="dialog loading" role="dialog" aria-modal="true" aria-label="Starting session">
            <Spinner>Starting your session</Spinner>
            <ul className="steps">
              <li className={online ? "done" : "active"}>{online ? `Connected to ${robotName}` : `Connecting to ${robotName} · ${elapsed} s`}</li>
              <li className={!online ? "" : state.loading_modules || state.profile?.preset === "base" ? "active" : "done"}>Loading {selected.length} modules</li>
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}
