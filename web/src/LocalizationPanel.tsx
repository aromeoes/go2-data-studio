import type { Item } from "./types";

export type LocalizationState = {
  status: string; message?: string; id?: string; space_name?: string;
  attempts?: number; confirmations?: number; required_confirmations?: number;
  fitness?: number; rmse?: number; seconds?: number;
  map_pose?: { x: number; y: number; yaw: number };
};

export function LocalizationPanel({ maps, selected, state, connection, disabled, onSelect, onConfirm }: {
  maps: Item[]; selected?: string | null; state?: LocalizationState;
  connection: string; disabled: boolean; onSelect: (id: string | null) => void; onConfirm?: () => void;
}) {
  const ready = maps.filter(m => m.status === "ready");
  const current = ready.find(m => m.id === selected);
  const online = connection === "online";
  const status = !selected ? "Live map" : !online ? "Waiting for connection"
    : state?.status === "localized" ? "Localized"
    : state?.status === "candidate" ? "Check location on map"
    : state?.status === "verifying" ? "Verifying alignment"
    : state?.status === "error" ? "Localization error"
    : state?.status === "inactive" ? "Enable mapping in Session setup" : "Localizing";
  return <section className="localization-panel" aria-label="Saved-map localization">
    <div className="localization-controls">
      <label htmlFor="localization-map">Reference map</label>
      <select id="localization-map" value={selected || ""} disabled={disabled}
        title="Pause movement and save recording before changing maps. The session reconnects with movement idle."
        onChange={e => onSelect(e.target.value || null)}>
        <option value="">Live map only</option>
        {selected && !current && <option value={selected}>Selected map · {selected.slice(0, 6)}</option>}
        {ready.map(m => <option key={m.id} value={m.id}>
          {new Date(m.created * 1000).toLocaleString()} · {m.id.slice(0, 6)}
        </option>)}
      </select>
      {selected && <button disabled={disabled} onClick={() => onSelect(selected)}>Retry</button>}
    </div>
    <div role="status" aria-live="polite"><strong>{status}</strong>
      {selected && online && state?.message && <span>{state.message}</span>}
    </div>
    {selected && online && state?.status === "candidate" && <button disabled={disabled} onClick={onConfirm}>Confirm robot location</button>}
    {selected && online && state && <small>
      {state.space_name && <span>{state.space_name} · </span>}
      {state.attempts !== undefined && <span>Attempts {state.attempts} · </span>}
      {state.fitness !== undefined && <span title="Fraction of scan points with a map correspondence. This is not a probability of being correctly localized.">Overlap {(state.fitness * 100).toFixed(0)}% · </span>}
      {state.rmse !== undefined && <span>Fit error {(state.rmse * 100).toFixed(1)} cm</span>}
      {state.status === "localized" && state.map_pose && <span> · Map X {state.map_pose.x.toFixed(2)}, Y {state.map_pose.y.toFixed(2)} m</span>}
    </small>}
    {selected && <small>Navigation waits for a confirmed alignment. Teleop stays available. Retry reconnects with movement idle.</small>}
  </section>;
}
