/** Connect your robot: scan saved robots, offer the one found, list all, add new hardware. */
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Plus, RefreshCw } from "lucide-react";
import type { State } from "../types";
import type { SavedRobot, SetupCatalog } from "../SessionSetup";
import { baseProfile } from "./modules";
import { api, get, RobotPicture, robotLabel, Spinner, type Notify } from "./ui";

const FOUND_SECONDS = 15;

export function Connect({ state, notify, onConnecting }: { state: State; notify: Notify; onConnecting: () => void }) {
  const [robots, setRobots] = useState<SavedRobot[] | null>(null);
  const [reach, setReach] = useState<Record<string, string>>({});
  const [scanning, setScanning] = useState(false);
  const [found, setFound] = useState<SavedRobot | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const offered = useRef(new Set<string>());
  const scanId = useRef(0);

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
      await api("/connect", { robot_id: robot.id, profile: baseProfile(robot.kind) });
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
        {adding && (
          <AddRobot
            notify={notify}
            onCancel={robots?.length ? () => setAdding(false) : undefined}
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
