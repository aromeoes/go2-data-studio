/** Connect your robot: scan saved robots, offer the one found, list all, add new hardware. */
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Plus, RefreshCw } from "lucide-react";
import type { SavedRobot, SetupCatalog, State } from "../types";
import { api, get, RobotPicture, robotLabel, Spinner, type Notify } from "./ui";

const FOUND_SECONDS = 15;

export function Connect({
  state,
  notify,
  onConnecting,
  onLibrary,
}: {
  state: State;
  notify: Notify;
  onConnecting: () => void;
  onLibrary: () => void;
}) {
  const [robots, setRobots] = useState<SavedRobot[] | null>(null);
  const [reach, setReach] = useState<Record<string, string>>({});
  const [scanning, setScanning] = useState(false);
  const [found, setFound] = useState<SavedRobot | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [byIp, setByIp] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [ip, setIp] = useState(state.ip || "");
  const offered = useRef(new Set<string>());
  const scanId = useRef(0);

  const recordings = state.segments.filter((s) => ["closed", "interrupted"].includes(s.status)).slice(0, 8);
  const spaceOf = (segment: State["segments"][number]) => {
    const session = state.sessions.find((x) => x.id === segment.parent);
    return state.spaces.find((x) => x.id === session?.parent)?.name || "Recording";
  };

  async function scan() {
    // Only the latest scan may update the screen or offer a robot.
    const id = ++scanId.current;
    setScanning(true);
    try {
      const catalog = await get<SetupCatalog>("/setup");
      setRobots(catalog.robots);
      if (!catalog.robots.length) {
        setAdding(true);
        return;
      }
      const [availability] = await Promise.all([
        get<Record<string, string>>("/robots/availability"),
        new Promise((done) => setTimeout(done, 1200)), // Keep the scanning state readable.
      ]);
      if (id !== scanId.current) return;
      setReach(availability);
      // Offer the first reachable robot once per visit to this screen.
      const first = catalog.robots.find((r) => availability[r.id] === "reachable" && !offered.current.has(r.id));
      if (first) {
        offered.current.add(first.id);
        setFound(first);
      }
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      if (id === scanId.current) setScanning(false);
    }
  }
  useEffect(() => {
    void scan();
    return () => {
      scanId.current++;
    };
  }, []);

  async function connect(robot: SavedRobot) {
    setFound(null);
    setBusy(true);
    try {
      // The backend connects with the required modules only; START adds the rest.
      await api("/connect", { robot_id: robot.id });
      onConnecting();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="screen">
      <header className="bar">
        <span className="wordmark small">DIMENSIONAL</span>
        <button onClick={onLibrary}>Recordings</button>
        <span className="muted">{state.cloud?.account?.email || "Local only"}</span>
      </header>
      <section className="card connect">
        <div className="row">
          <h1>Robots available</h1>
          <button onClick={() => setAdding(true)} disabled={adding}>
            <Plus size={16} /> Add robot
          </button>
          <button onClick={() => void scan()} disabled={scanning}>
            <RefreshCw size={16} /> Scan again
          </button>
        </div>
        {scanning && <Spinner>Scanning available robots</Spinner>}
        {robots && !robots.length && !adding && <p className="hint">No saved robots yet. Add one, or replay a recording.</p>}
        {robots && robots.length > 0 && (
          <div className="robot-grid">
            {robots.map((r) => (
              <button key={r.id} className="robot-card" disabled={busy} onClick={() => void connect(r)}>
                <RobotPicture kind={r.kind} />
                <strong>{r.name}</strong>
                <span>
                  {robotLabel(r.kind)} · {r.ip}
                </span>
                <small className={reach[r.id] === "reachable" ? "ok" : ""}>
                  {scanning ? "Checking…" : reach[r.id] === "reachable" ? "Found on this network" : reach[r.id] ? "Not found on this network" : "Saved"}
                </small>
              </button>
            ))}
          </div>
        )}
        {!adding &&
          (byIp ? (
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                setBusy(true);
                api("/connect", { ip })
                  .then(onConnecting)
                  .catch((err) => notify(err.message, "error"))
                  .finally(() => setBusy(false));
              }}
            >
              <label className="inline">
                Go2 IP address
                <input required autoFocus inputMode="decimal" placeholder="192.168.1.20" value={ip} onChange={(e) => setIp(e.target.value)} />
              </label>
              <button className="primary" disabled={busy}>
                Connect
              </button>
              <button type="button" className="link" onClick={() => setByIp(false)}>
                Cancel
              </button>
            </form>
          ) : (
            <div className="row">
              <button className="link connect-by-ip" onClick={() => setByIp(true)}>
                Connect once by IP without saving
              </button>
              {recordings.length > 0 && (
                <button className="link" onClick={() => setReplaying(!replaying)} aria-expanded={replaying}>
                  Replay a recording
                </button>
              )}
            </div>
          ))}
        {replaying && !adding && (
          <ul className="list" aria-label="Recordings to replay">
            {recordings.map((s) => (
              <li key={s.id}>
                <div>
                  <strong>{spaceOf(s)}</strong>
                  <small>
                    {new Date(s.created * 1000).toLocaleString("en-US", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })} ·{" "}
                    {((s.stats?.physical_bytes || 0) / 1e9).toFixed(2)} GB · {((s.stats?.duration || 0) / 60).toFixed(1)} min
                  </small>
                </div>
                <button
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    api("/connect", { segment_id: s.id })
                      .then(onConnecting)
                      .catch((err) => notify(err.message, "error"))
                      .finally(() => setBusy(false));
                  }}
                >
                  Replay
                </button>
              </li>
            ))}
          </ul>
        )}
        {adding && (
          <AddRobot
            notify={notify}
            onCancel={() => setAdding(false)}
            onSaved={() => {
              setAdding(false);
              void scan();
            }}
          />
        )}
      </section>
      {found && <FoundModal robot={found} onConnect={() => void connect(found)} onClose={() => setFound(null)} />}
    </main>
  );
}

/** "Robot found" prompt with a visible 15 second window. Never connects on its own. */
function FoundModal({ robot, onConnect, onClose }: { robot: SavedRobot; onConnect: () => void; onClose: () => void }) {
  const [left, setLeft] = useState(FOUND_SECONDS);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const began = Date.now();
    const id = setInterval(() => {
      const remaining = FOUND_SECONDS - (Date.now() - began) / 1000;
      if (remaining <= 0) close.current();
      else setLeft(remaining);
    }, 100);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="overlay">
      <section role="dialog" aria-modal="true" aria-labelledby="found-title" className="dialog found">
        <h2 id="found-title">Robot found</h2>
        <div className="found-card">
          <RobotPicture kind={robot.kind} large />
          <div>
            <strong>{robot.name}</strong>
            <span>
              {robotLabel(robot.kind)} · {robot.ip}
            </span>
          </div>
        </div>
        <div className="timer" role="timer" aria-label={`${Math.ceil(left)} seconds left to connect`}>
          <i style={{ width: `${(left / FOUND_SECONDS) * 100}%` }} />
        </div>
        <button className="primary" autoFocus onClick={onConnect}>
          Connect
        </button>
        <button className="link" onClick={onClose}>
          Cancel
        </button>
      </section>
    </div>
  );
}

const HARDWARE = [
  { kind: "go2", name: "Unitree Go2", ipHelp: "Unitree app: Device › Network › STA IP address." },
  { kind: "vector", name: "Anki Vector", ipHelp: "Shown on Vector's screen or in the wire-pod setup page." },
];

function AddRobot({ notify, onSaved, onCancel }: { notify: Notify; onSaved: () => void; onCancel?: () => void }) {
  const [kind, setKind] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", ip: "", serial: "", sdk_config: "" });
  const [busy, setBusy] = useState(false);
  const hardware = HARDWARE.find((h) => h.kind === kind);
  const field = (key: keyof typeof form) => ({
    value: form[key],
    onChange: (e: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value }),
  });
  return (
    <section className="add-robot" aria-label="Add robot">
      <h2>Add robot</h2>
      {!hardware ? (
        <>
          <p>Which robot do you want to connect?</p>
          <div className="robot-grid">
            {HARDWARE.map((h, i) => (
              <button
                key={h.kind}
                className="robot-card"
                autoFocus={i === 0}
                onClick={() => {
                  setKind(h.kind);
                  setForm({ ...form, name: h.kind === "vector" ? "My Vector" : "My Go2" });
                }}
              >
                <RobotPicture kind={h.kind} />
                <strong>{h.name}</strong>
              </button>
            ))}
          </div>
          {onCancel && (
            <button className="link" onClick={onCancel}>
              Cancel
            </button>
          )}
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setBusy(true);
            api("/robots", { ...form, kind })
              .then(() => {
                notify(`${form.name} saved`);
                onSaved();
              })
              .catch((err) => notify(err.message, "error"))
              .finally(() => setBusy(false));
          }}
        >
          <label>
            Name
            <input required maxLength={80} autoFocus {...field("name")} />
          </label>
          <label>
            Wi-Fi IP address
            <input required placeholder="192.168.1.20" inputMode="decimal" {...field("ip")} />
            <small>{hardware.ipHelp}</small>
          </label>
          <label>
            {kind === "vector" ? "Serial number" : "Serial number (optional)"}
            <input required={kind === "vector"} maxLength={100} {...field("serial")} />
          </label>
          {kind === "vector" && (
            <label>
              SDK configuration on this computer
              <input placeholder="~/.anki_vector/sdk_config.ini" {...field("sdk_config")} />
              <small>From pairing Vector with wire-pod. Credentials stay on this device.</small>
            </label>
          )}
          <div className="row">
            <button type="button" onClick={() => setKind(null)}>
              Back
            </button>
            <button className="primary" disabled={busy}>
              Save robot
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
