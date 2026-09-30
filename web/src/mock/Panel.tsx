/** Floating controls for mock mode: choose the scenario and trigger events mid-flow. */
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { MockBackend, Scenario } from "./backend";

function Choice<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <label>
      {label}
      <select
        value={String(value)}
        onChange={(e) =>
          onChange(options.find(([v]) => String(v) === e.target.value)![0])
        }
      >
        {options.map(([v, text]) => (
          <option key={String(v)} value={String(v)}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function Panel({
  backend,
  save,
}: {
  backend: MockBackend;
  save: (scenario: Scenario) => void;
}) {
  // Collapsed by default so the panel never covers the app's own controls.
  const [open, setOpen] = useState(false);
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 400);
    return () => clearInterval(id);
  }, []);
  const scenario = backend.scenario;
  const set = (patch: Partial<Scenario>) => {
    backend.setScenario(patch);
    save(backend.scenario);
    setTick((n) => n + 1);
  };
  const online = backend.connection === "online";
  return (
    <aside className="mock-panel" aria-label="Mock mode controls">
      <button className="mock-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <strong>MOCK MODE</strong>
        <span>
          {backend.connection} · {backend.mode}
        </span>
        <span aria-hidden="true">{open ? "–" : "+"}</span>
      </button>
      {open && (
        <div className="mock-body">
          <p>Simulated backend, robot and cloud. Nothing leaves this page.</p>
          <h3>Scenario</h3>
          <Choice
            label="Device state at launch"
            value={scenario.start}
            options={[
              ["returning", "Returning user (robots, recordings)"],
              ["first-run", "First run (empty)"],
            ]}
            onChange={(start) => set({ start })}
          />
          <Choice
            label="DimOS Cloud account"
            value={scenario.account}
            options={[
              ["signed-in", "Signed in"],
              ["signed-out", "Signed out"],
            ]}
            onChange={(account) => set({ account })}
          />
          <Choice
            label="Robots on the network"
            value={scenario.network}
            options={[
              ["go2", "Go2 only"],
              ["both", "Go2 and Vector"],
              ["none", "None reachable"],
            ]}
            onChange={(network) => set({ network })}
          />
          <Choice
            label="Time to connect"
            value={scenario.connectSeconds}
            options={[
              [4, "Fast (4 s)"],
              [20, "Steam Deck typical (20 s)"],
              [50, "Slow (50 s)"],
            ]}
            onChange={(connectSeconds) => set({ connectSeconds })}
          />
          <Choice
            label="Time to start a session"
            value={scenario.sessionSeconds}
            options={[
              [4, "Fast (4 s)"],
              [23, "Steam Deck typical (23 s)"],
            ]}
            onChange={(sessionSeconds) => set({ sessionSeconds })}
          />
          <label className="mock-check">
            <input
              type="checkbox"
              checked={scenario.agentConfigured}
              onChange={(e) => set({ agentConfigured: e.target.checked })}
            />
            HumanCLI model configured
          </label>
          <h3>Trigger now</h3>
          {backend.cloud.login && (
            <div className="mock-row mock-attention">
              <button onClick={() => set({ account: "signed-in" })}>Approve cloud sign-in</button>
              <button onClick={() => backend.expireLogin()}>Expire code</button>
            </div>
          )}
          <div className="mock-row">
            <button disabled={!online} onClick={() => backend.dropConnection()}>
              Drop connection
            </button>
            <button
              disabled={!online}
              aria-pressed={backend.frozen}
              onClick={() => backend.freezeSensors(!backend.frozen)}
            >
              {backend.frozen ? "Resume sensors" : "Freeze sensors"}
            </button>
          </div>
          <label>
            Battery {Math.round(backend.battery)}%
            <input
              type="range"
              min={1}
              max={100}
              value={Math.round(backend.battery)}
              onChange={(e) => (backend.battery = Number(e.target.value))}
            />
          </label>
          <label className="mock-check">
            <input
              type="checkbox"
              checked={backend.failNextUpload}
              onChange={(e) => (backend.failNextUpload = e.target.checked)}
            />
            Fail the next upload at 60%
          </label>
          <label className="mock-check">
            <input
              type="checkbox"
              checked={backend.failNextMap}
              onChange={(e) => (backend.failNextMap = e.target.checked)}
            />
            Fail the next map generation
          </label>
          <div className="mock-row">
            <button onClick={() => backend.reset()}>Reset all</button>
            <button
              onClick={() =>
                window.open(
                  location.pathname,
                  "dimensional-deck",
                  "width=1280,height=800",
                )
              }
            >
              Deck size window
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}

export function mountPanel(backend: MockBackend, save: (scenario: Scenario) => void) {
  const host = document.createElement("div");
  document.body.append(host);
  createRoot(host).render(<Panel backend={backend} save={save} />);
}
