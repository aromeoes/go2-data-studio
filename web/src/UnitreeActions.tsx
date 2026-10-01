import React, { useEffect, useRef, useState } from "react";
export type UnitreeAction = { name: string; description: string; category: string; available: boolean; reason?: string | null; api_id: number };
export function UnitreeActions({ connected, mode, stopped, epoch, enabled, api }: {
  connected: boolean; mode: string; stopped: boolean; epoch: number; enabled: boolean;
  api: (path: string, data?: unknown) => Promise<any>;
}) {
  const [actions, setActions] = useState<UnitreeAction[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{name: string; epoch: number} | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (confirm) dialog.current?.showModal(); }, [confirm]);
  const current = actions.find(a => a.name === selected);
  const reason = !connected ? "Connect Go2 to run actions." : !enabled ? "Enable manual driving in Session setup." : stopped ? "Release Emergency stop first." : mode !== "idle" ? "Pause Teleop, exploration or HumanCLI before running an action." : current?.reason;
  async function load() {
    if (actions.length || loading) return;
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/unitree/actions");
      if (!response.ok) throw Error("Could not load DimOS actions. Reopen this panel to retry.");
      const data = await response.json(); setActions(data.actions);
      setSelected(data.actions.find((a: UnitreeAction) => a.name === "Hello")?.name || data.actions[0]?.name || "");
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  return <details className="unitree-actions" onToggle={e => { if (e.currentTarget.open) void load(); }}>
    <summary>Unitree actions <span>{actions.length ? `(${actions.length})` : ""}</span></summary>
    <p>From DimOS UnitreeSkillContainer. Support depends on the robot firmware.</p>
    {loading && <p role="status">Loading actions…</p>}
    {actions.length > 0 && <>
      <label>Find an action<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Jump, pounce, Hello…" /></label>
      <label>Action<select size={6} value={selected} onChange={e => { setSelected(e.target.value); setResult(""); }}>
        {actions.filter(a => `${a.name} ${a.description} ${a.category}`.toLowerCase().includes(query.toLowerCase())).map(a => <option key={a.name} value={a.name}>{a.name} · {a.category}{a.available ? "" : " · needs arguments"}</option>)}
      </select></label>
      {current && <p>{current.description}</p>}
      {reason && <p role="status">{reason}</p>}
      <button disabled={!!reason || !current?.available || busy} onClick={() => { setConfirm({name: selected, epoch}); setError(""); setResult(""); }}>Run selected action</button>
    </>}
    {error && <p role="alert" className="setup-error">{error}</p>}
    {result && <p role="status">{result}</p>}
    {confirm && <dialog ref={dialog} role="alertdialog" aria-labelledby="unitree-action-title" className="dialog upload-dialog" onCancel={() => { if (!busy) setConfirm(null); }}>
      <h2 id="unitree-action-title">Run {confirm.name}?</h2>
      <p>This sends the action to Go2 now. Dynamic actions can jump, flip or move the robot. Check the surrounding space before running it.</p>
      <p>One command is sent. Wait for the robot to finish before selecting another action.</p>
      {error && <p role="alert">{error}</p>}
      <div className="setup-actions"><button autoFocus disabled={busy} onClick={() => setConfirm(null)}>Cancel</button><button className="primary" disabled={!!reason || busy || confirm.epoch !== epoch} onClick={async () => {
        setBusy(true); setError("");
        try { const response = await api("/unitree/action", {name: confirm.name, confirmed: confirm.name, epoch: confirm.epoch}); setResult(response.message); setConfirm(null); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
      }}>{busy ? "Sending…" : `Run ${confirm.name}`}</button></div>
    </dialog>}
  </details>;
}
