import React, { useEffect, useState } from "react";
import {
  Bot,
  Check,
  ChevronRight,
  Layers,
  Plus,
  Settings2,
  Wifi,
  X,
} from "lucide-react";
import type { State } from "./types";
import { ConnectionProgress } from "./ConnectionProgress";

export type SessionProfile = {
  preset: string;
  enabled: string[];
  kind?: string;
};
export type SavedRobot = {
  id: string;
  name: string;
  kind: string;
  ip: string;
  serial: string;
  sdk_config?: string;
  profile: SessionProfile;
};
export type Capability = {
  id: string;
  name: string;
  detail: string;
  requires: string[];
  modules: string[];
};
export type SetupCatalog = {
  robots: SavedRobot[];
  embodiments?: Record<string, Omit<SetupCatalog, "robots" | "embodiments">>;
  capabilities: Capability[];
  presets: {
    id: string;
    name: string;
    description: string;
    enabled: string[];
  }[];
  required_modules: string[];
};

// Selecting a feature includes its prerequisites. Removing one removes dependents.
export function toggleCapability(
  selected: string[],
  id: string,
  on: boolean,
  capabilities: Capability[],
) {
  const result = new Set(selected);
  function include(key: string) {
    if (result.has(key)) return;
    result.add(key);
    capabilities.find((c) => c.id === key)?.requires.forEach(include);
  }
  if (on) include(id);
  else {
    result.delete(id);
    let changed = true;
    while (changed) {
      changed = false;
      for (const c of capabilities)
        if (result.has(c.id) && c.requires.some((r) => !result.has(r))) {
          result.delete(c.id);
          changed = true;
        }
    }
  }
  return capabilities.filter((c) => result.has(c.id)).map((c) => c.id);
}

export function SessionSetup({
  state,
  api,
  refresh,
  pause,
  onApplied,
}: {
  state: State;
  api: (path: string, body?: unknown) => Promise<any>;
  refresh: () => Promise<void>;
  pause: () => Promise<void>;
  onApplied: () => void;
}) {
  const [catalog, setCatalog] = useState<SetupCatalog | null>(null);
  const [selected, setSelected] = useState(state.robot_id || "");
  const [availability, setAvailability] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    ip: state.ip || "",
    serial: "",
    kind: "go2",
    sdk_config: "",
  });
  const [draft, setDraft] = useState<SessionProfile | null>(null);
  const [customize, setCustomize] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const offline = state.connection === "offline";
  const preview = state.profile?.preset === "preview";
  const expanded = offline || preview || editing;
  const currentRobot = catalog?.robots.find((r) => r.id === state.robot_id);
  const selectedRobot = catalog?.robots.find((r) => r.id === selected);
  const kind =
    (offline ? selectedRobot : currentRobot)?.kind || state.robot_kind || "go2";
  const options = catalog?.embodiments?.[kind] || catalog;
  async function load() {
    const response = await fetch("/api/setup");
    if (!response.ok) throw Error("Could not load saved robots");
    const value: SetupCatalog = await response.json();
    setCatalog(value);
    setSelected(
      (previous) => previous || state.robot_id || value.robots[0]?.id || "",
    );
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!catalog) return;
    const robot = catalog.robots.find(
      (r) => r.id === (state.robot_id || selected),
    );
    const initial =
      !offline &&
      state.profile?.preset &&
      !["preview", "legacy"].includes(state.profile.preset)
        ? state.profile
        : robot?.profile || {
            preset: "map-record",
            enabled: catalog.presets.find((p) => p.id === "map-record")!
              .enabled,
          };
    setDraft(initial);
  }, [state.robot_id, state.profile?.preset, selected, catalog]);
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function apply() {
    if (!draft) return;
    await api("/session/profile", {
      ...draft,
      robot_id: state.robot_id ?? null,
    });
    onApplied();
    setEditing(false);
    await load();
    await refresh();
  }
  if (!catalog || !options || !draft)
    return (
      <section className="session-setup panel">
        <p role="status">{error || "Loading robot setup…"}</p>
      </section>
    );
  const currentPreset = options.presets.find(
    (p) => p.id === state.profile?.preset,
  );
  const canExplore = draft.enabled.includes("exploration");
  return (
    <section
      className="session-setup panel"
      aria-label="Robot and session setup"
    >
      <div className="panel-head">
        <div>
          <Bot size={18} />
          <strong>
            {offline
              ? "My robots"
              : currentRobot?.name ||
                (state.replay ? "Recording replay" : "Go2")}
          </strong>
          {!expanded && (
            <span className="tiny-pill">
              {currentPreset?.name || "Custom session"}
            </span>
          )}
        </div>
        {!offline && !preview && (
          <button
            onClick={() => {
              setEditing(!editing);
            }}
          >
            <Settings2 size={15} />
            {editing ? "Close setup" : "Session setup"}
          </button>
        )}
      </div>
      {error && (
        <p className="setup-error" role="alert">
          {error}
        </p>
      )}
      <ConnectionProgress connection={state.connection} kind={kind} replay={state.replay} />
      {!offline && !expanded && (
        <div className="session-summary">
          <span>
            <Check size={14} /> {state.modules?.length || 0} modules ·{" "}
            {state.profile?.enabled.length || 0} capabilities
          </span>
          <span>
            {state.profile?.enabled.includes("exploration")
              ? "Explore available"
              : "Exploration disabled"}
          </span>
        </div>
      )}
      {expanded && (
        <div className="setup-body">
          {offline ? (
            <>
              <div className="setup-intro">
                <div>
                  <h2>Choose your robot</h2>
                  <p>
                    Connect for camera and status. App controls start disabled.
                  </p>
                </div>
                <button
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      const response = await fetch("/api/robots/availability");
                      if (!response.ok)
                        throw Error("Could not check robot availability");
                      setAvailability(await response.json());
                    })
                  }
                >
                  <Wifi size={14} />
                  Check availability
                </button>
              </div>
              <div className="robot-cards">
                {catalog.robots.map((r) => (
                  <div
                    className={
                      "robot-card " + (selected === r.id ? "selected" : "")
                    }
                    key={r.id}
                  >
                    <button
                      className="robot-select"
                      aria-pressed={selected === r.id}
                      onClick={() => {
                        setSelected(r.id);
                        setAdding(false);
                      }}
                    >
                      <Bot size={24} />
                      <strong>{r.name}</strong>
                      <span>
                        {r.kind === "vector" ? "Anki Vector" : "Unitree Go2"} ·{" "}
                        {r.ip}
                      </span>
                      <small>
                        {availability[r.id] === "reachable"
                          ? "Reachable · not yet connected"
                          : availability[r.id] === "unreachable"
                            ? "Not reachable at saved IP"
                            : "Saved robot"}
                      </small>
                    </button>
                    <button
                      className="robot-edit"
                      onClick={() => {
                        setEditId(r.id);
                        setForm({
                          name: r.name,
                          ip: r.ip,
                          serial: r.serial,
                          kind: r.kind,
                          sdk_config: r.sdk_config || "",
                        });
                        setAdding(true);
                      }}
                    >
                      Edit
                    </button>
                  </div>
                ))}
              </div>
              <div className="setup-actions">
                <button
                  onClick={() => {
                    setEditId(null);
                    setAdding(!adding);
                    setForm({
                      name: "My robot",
                      ip: "",
                      serial: "",
                      kind: "go2",
                      sdk_config: "",
                    });
                  }}
                >
                  <Plus size={15} />
                  Add robot
                </button>
                <button
                  className="primary"
                  disabled={!selectedRobot || busy || adding}
                  onClick={() =>
                    run(async () => {
                      await api("/connect", { robot_id: selected });
                      await refresh();
                    })
                  }
                >
                  <Wifi size={15} />
                  Connect {selectedRobot?.name || "robot"}
                </button>
              </div>
              {adding && (
                <form
                  className="robot-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run(async () => {
                      const saved = await api(
                        editId ? `/robots/${editId}` : "/robots",
                        form,
                      );
                      setSelected(saved.id);
                      setAdding(false);
                      await load();
                    });
                  }}
                >
                  <label>
                    Robot type
                    <select
                      aria-label="Robot type"
                      value={form.kind}
                      disabled={!!editId}
                      onChange={(e) =>
                        setForm({ ...form, kind: e.target.value })
                      }
                    >
                      <option value="go2">Unitree Go2</option>
                      <option value="vector">Anki Vector</option>
                    </select>
                  </label>
                  <label>
                    Name
                    <input
                      required
                      maxLength={80}
                      value={form.name}
                      onChange={(e) =>
                        setForm({ ...form, name: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Wi-Fi IP address
                    <input
                      required
                      placeholder="192.168.1.73"
                      value={form.ip}
                      onChange={(e) => setForm({ ...form, ip: e.target.value })}
                    />
                  </label>
                  <label>
                    {form.kind === "vector"
                      ? "Vector serial number"
                      : "Serial number (optional)"}
                    <input
                      maxLength={100}
                      required={form.kind === "vector"}
                      value={form.serial}
                      onChange={(e) =>
                        setForm({ ...form, serial: e.target.value })
                      }
                    />
                  </label>
                  {form.kind === "vector" && (
                    <label>
                      SDK configuration on this computer
                      <input
                        placeholder="~/.anki_vector/sdk_config.ini"
                        value={form.sdk_config}
                        onChange={(e) =>
                          setForm({ ...form, sdk_config: e.target.value })
                        }
                      />
                      <small>
                        Paired wire-pod SDK config and certificate. Credentials
                        stay on this device.
                      </small>
                    </label>
                  )}
                  <div className="setup-actions">
                    <button type="button" onClick={() => setAdding(false)}>
                      Cancel
                    </button>
                    <button className="primary" disabled={busy}>
                      Save robot
                    </button>
                  </div>
                </form>
              )}
              <p className="setup-footnote">
                Go2 and Anki Vector use their own local pairing credentials.
                Vector connects with its saved session. Driving starts only when
                you take control.
              </p>
            </>
          ) : (
            <>
              <div className="setup-intro">
                <div>
                  <h2>
                    {preview
                      ? "What would you like to do?"
                      : "Configure your next session"}
                  </h2>
                  <p>Choose a preset, then customize its capabilities.</p>
                </div>
              </div>
              <div className="preset-cards">
                {options.presets.map((p) => (
                  <button
                    key={p.id}
                    className={
                      "preset-card " + (draft.preset === p.id ? "selected" : "")
                    }
                    aria-pressed={draft.preset === p.id}
                    disabled={busy}
                    onClick={() => {
                      setDraft({ preset: p.id, enabled: [...p.enabled] });
                      setNotice("");
                    }}
                  >
                    <strong>{p.name}</strong>
                    <span>{p.description}</span>
                    {p.enabled.includes("exploration") && (
                      <small>
                        <Check size={13} /> Includes autonomous exploration
                      </small>
                    )}
                  </button>
                ))}
              </div>
              <div className="setup-actions">
                <span className="explore-availability">
                  {canExplore
                    ? "Explore enabled by mapping + navigation"
                    : kind === "vector"
                      ? "Vector: native faces, expressions and bounded movement"
                      : "Explore unavailable in this configuration"}
                </span>
                <button onClick={() => setCustomize(!customize)}>
                  <Settings2 size={15} />
                  {customize ? "Hide options" : "Customize"}
                </button>
              </div>
              {customize && (
                <div className="capability-list">
                  {options.capabilities.map((c) => (
                    <label
                      key={c.id}
                      className="capability-option"
                      title={c.detail + (c.requires.length ? " Requires " + c.requires.map(id => options.capabilities.find(x => x.id === id)?.name).join(", ") + "." : "")}
                    >
                      <input
                        type="checkbox"
                        checked={draft.enabled.includes(c.id)}
                        disabled={busy}
                        onChange={(e) => {
                          const next = toggleCapability(
                            draft.enabled,
                            c.id,
                            e.target.checked,
                            options.capabilities,
                          );
                          const removed = draft.enabled.filter(
                            (x) => !next.includes(x) && x !== c.id,
                          );
                          setNotice(
                            removed.length
                              ? "Also disabled: " +
                                  removed
                                    .map(
                                      (x) =>
                                        options.capabilities.find(
                                          (c) => c.id === x,
                                        )?.name,
                                    )
                                    .join(", ")
                              : "Dependencies are included automatically.",
                          );
                          setDraft({ ...draft, enabled: next });
                        }}
                      />
                      <strong>{c.name}</strong>
                    </label>
                  ))}
                </div>
              )}
              {notice && (
                <p role="status" className="setup-footnote">
                  {notice}
                </p>
              )}
              <details className="module-plan">
                <summary>
                  <Layers size={14} />
                  Advanced: modules and dependencies
                </summary>
                <p>Required for every connection</p>
                <ul>
                  {options.required_modules.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
                <p>Selected capabilities</p>
                <ul>
                  {options.capabilities
                    .filter((c) => draft.enabled.includes(c.id))
                    .map((c) => (
                      <li key={c.id}>
                        <strong>{c.name}:</strong> {c.modules.join(", ")}
                      </li>
                    ))}
                </ul>
                <small>
                  Sensor and recording options configure existing modules.
                  HumanCLI and voice run as application services. Changes
                  rebuild the session; they do not hot-swap modules.
                </small>
              </details>
              {state.session && (
                <p className="setup-error">
                  Save your recording before changing the session.
                </p>
              )}
              <div className="setup-actions">
                <p className="setup-footnote">
                  Starting enables capabilities. It never starts driving,
                  exploring, or recording automatically.
                </p>
                <button
                  className="primary"
                  disabled={
                    busy || state.connection !== "online" || !!state.session
                  }
                  onClick={() => void run(async () => {
                    if (state.mode !== "idle") await pause();
                    await apply();
                  })}
                >
                  {state.connection !== "online" ? "Waiting for connection…" : busy ? "Starting session…" : preview ? "Start session" : "Apply changes"}
                  <ChevronRight size={15} />
                </button>
              </div>

            </>
          )}
        </div>
      )}
    </section>
  );
}
