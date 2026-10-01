/**
 * Recordings, generated maps and activity for one space, with their dialogs.
 * Shown below the fold in a session and on the Recordings screen without a robot.
 */
import { useState } from "react";
import { ArrowUpRight, Copy, Download, Folder, Play, Plus, Trash2 } from "lucide-react";
import type { Item, State } from "../types";
import { BackupControl } from "../Cloud";
import { GenerateMapButton } from "../GenerateMapButton";
import { api, Dialog, gb, type Notify } from "./ui";

const LABELS: Record<string, string> = {
  recording: "Recording",
  closed: "Saved",
  interrupted: "Interrupted",
  importing: "Importing",
  queued: "Queued",
  running: "Generating",
  ready: "Ready",
  failed: "Error",
  cancelled: "Cancelled",
};
const date = (s: number) =>
  new Date(s * 1000).toLocaleString("en-US", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export function Archive({
  state,
  spaceId,
  notify,
  beforeMap = async () => {},
  onReplay,
}: {
  state: State;
  spaceId: string;
  notify: Notify;
  /** Runs before map generation, e.g. pausing robot control during a session. */
  beforeMap?: () => Promise<void>;
  /** Replays a recording; omitted while a robot is connected. */
  onReplay?: (segment: Item) => void;
}) {
  const [tab, setTab] = useState<"recordings" | "maps" | "activity">("recordings");
  const [busy, setBusy] = useState("");
  const [importing, setImporting] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [deleting, setDeleting] = useState<Item | null>(null);
  const [quality, setQuality] = useState<Item | null>(null);
  const [resolution, setResolution] = useState(0.1);
  const [pgo, setPgo] = useState(true);
  const space = state.spaces.find((s) => s.id === spaceId);
  const sessions = state.sessions.filter((s) => s.parent === spaceId);
  const segments = state.segments.filter((s) => sessions.some((x) => x.id === s.parent));
  const maps = state.maps.filter((m) => segments.some((s) => s.id === m.parent));
  const source = (s: Item) => sessions.find((x) => x.id === s.parent)?.source;

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
  const open = (id: string, what: string) => void run("open", () => api(`/open/${id}/${what}`));
  const copy = async (path?: string) => {
    if (!path) return;
    await navigator.clipboard.writeText(path);
    notify("Path copied");
  };

  return (
    <>
      <section className="card archive" aria-label="Saved data">
        <div className="row">
          <div className="tabs" role="tablist">
            {(
              [
                ["recordings", `Recordings (${segments.length})`],
                ["maps", `Generated maps (${maps.length})`],
                ["activity", "Activity"],
              ] as const
            ).map(([id, label]) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </div>
          <span className="spacer" />
          <button disabled={!space} onClick={() => setImporting(true)}>
            <Plus size={14} /> Import recording
          </button>
        </div>
        {tab === "recordings" && (
          <>
            <div className="row">
              <label className="inline">
                Map resolution
                <select value={resolution} onChange={(e) => setResolution(Number(e.target.value))}>
                  <option value={0.1}>10 cm · fast</option>
                  <option value={0.05}>5 cm · detailed</option>
                </select>
              </label>
              <label className="inline">
                <input type="checkbox" checked={pgo} onChange={(e) => setPgo(e.target.checked)} />
                Optimize trajectory (PGO)
              </label>
              <small>Each generation creates a new map version.</small>
            </div>
            <ul className="list">
              {segments.map((s, i) => (
                <li key={s.id}>
                  <div>
                    <strong>Segment {segments.length - i}</strong>
                    <small>
                      {date(s.created)} · {gb(s.stats?.physical_bytes)} GB · {((s.stats?.duration || 0) / 60).toFixed(1)} min ·{" "}
                      {LABELS[s.status] || s.status} · {source(s) === "replay" ? "Replay" : source(s) === "import" ? "Imported" : "Robot"}
                    </small>
                    <code title={s.path}>{s.path}</code>
                  </div>
                  <BackupControl segment={s} spaceName={space?.name} cloud={state.cloud} action={run} api={api} pending={!!busy} />
                  <GenerateMapButton
                    recording={s.status === "recording"}
                    pending={!!busy}
                    mode={state.mode}
                    onGenerate={() =>
                      void run("map", async () => {
                        await beforeMap();
                        await api("/maps", { segment_id: s.id, voxel: resolution, pgo });
                        setTab("maps");
                        notify("Generating the map on this device.");
                      })
                    }
                  />
                  <button aria-label="Show recording in file manager" title="Show in file manager" onClick={() => open(s.id, "raw")}>
                    <Folder size={15} />
                  </button>
                  <button aria-label="Copy recording path" title="Copy path" onClick={() => void copy(s.path)}>
                    <Copy size={15} />
                  </button>
                  <button
                    disabled={!onReplay || !!busy || !["closed", "interrupted"].includes(s.status)}
                    title={onReplay ? "Replay this recording" : "End the session to replay a recording"}
                    onClick={() => onReplay?.(s)}
                  >
                    <Play size={13} /> Replay
                  </button>
                  {s.backup?.status !== "complete" && (
                    <button
                      aria-label={`Delete segment ${s.id.slice(0, 6)}`}
                      title="Delete local segment and its generated maps"
                      disabled={
                        !!busy ||
                        ["recording", "importing"].includes(s.status) ||
                        state.session?.id === s.parent ||
                        state.cloud?.active_segment === s.id ||
                        ["preparing", "uploading", "verifying"].includes(s.backup?.status || "") ||
                        state.maps.some((m) => m.parent === s.id && ["queued", "running"].includes(m.status))
                      }
                      onClick={() => setDeleting(s)}
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </li>
              ))}
              {!segments.length && <li className="muted">No recordings in {space?.name || "this space"} yet.</li>}
            </ul>
          </>
        )}
        {tab === "maps" && (
          <ul className="list">
            {maps.map((m, i) => (
              <li key={m.id}>
                <div>
                  <strong>Map {maps.length - i}</strong>
                  <small>
                    {date(m.created)} · {(m.voxel || 0.1) * 100} cm · {LABELS[m.status] || m.status}
                  </small>
                  {m.error && <small className="error-text">{m.error}</small>}
                </div>
                <button aria-label="Show map folder" onClick={() => open(m.id, "folder")}>
                  <Folder size={15} />
                </button>
                {m.log && (
                  <a className="button" href={`/api/files/${m.id}/log`} target="_blank" rel="noreferrer">
                    Log
                  </a>
                )}
                {m.status === "ready" && (
                  <>
                    <button onClick={() => setQuality(m)}>Quality</button>
                    <button className="primary" disabled={!m.rerun_path} onClick={() => open(m.id, "rerun")}>
                      Open in Rerun <ArrowUpRight size={14} />
                    </button>
                    <a className="button" aria-label="Download map" href={`/api/files/${m.id}/map`}>
                      <Download size={15} />
                    </a>
                  </>
                )}
                {["queued", "running"].includes(m.status) && (
                  <button onClick={() => void run("cancel-map", () => api(`/maps/${m.id}/cancel`))}>Cancel</button>
                )}
              </li>
            ))}
            {!maps.length && <li className="muted">Generate a map from a recording.</li>}
          </ul>
        )}
        {tab === "activity" && (
          <ul className="list">
            {state.events.map((e) => (
              <li key={e.id}>
                <small>{date(e.ts)}</small> {e.message}
              </li>
            ))}
            {!state.events.length && <li className="muted">Session activity will appear here.</li>}
          </ul>
        )}
      </section>

      {importing && (
        <Dialog label="Import recording" onClose={() => setImporting(false)}>
          <h2>Import recording</h2>
          <form
            className="dialog-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run("import", async () => {
                await api("/import", { space_id: spaceId, path: importPath });
                setImporting(false);
                setImportPath("");
                notify(`Importing into ${space?.name}.`);
              });
            }}
          >
            <label>
              Path to the DimOS .db file
              <input autoFocus required maxLength={2000} value={importPath} onChange={(e) => setImportPath(e.target.value)} placeholder="/path/to/recording.db" />
            </label>
            <p className="hint">The file is copied into {space?.name}. The original stays where it is.</p>
            <button className="primary" disabled={!!busy}>
              Import
            </button>
            <button type="button" onClick={() => setImporting(false)}>
              Cancel
            </button>
          </form>
        </Dialog>
      )}
      {deleting && (
        <Dialog label="Delete segment" onClose={() => busy !== "delete" && setDeleting(null)}>
          <h2>Delete segment {deleting.id.slice(0, 6)}?</h2>
          <p>
            This segment has no confirmed backup of its current data. Permanently delete the local recording and{" "}
            {state.maps.filter((m) => m.parent === deleting.id).length} generated maps? This cannot be undone. Existing cloud data and imported
            source files are kept.
          </p>
          <code>{deleting.path || deleting.folder}</code>
          <button autoFocus disabled={!!busy} onClick={() => setDeleting(null)}>
            Cancel
          </button>
          <button
            className="danger"
            disabled={!!busy}
            onClick={() => {
              setBusy("delete");
              api(`/segments/${deleting.id}/delete`, { confirmed: true })
                .then((result) => {
                  notify(result.warning || "Local segment and generated maps deleted.");
                  setDeleting(null);
                })
                .catch((e) => notify(e.message, "error"))
                .finally(() => setBusy(""));
            }}
          >
            {busy === "delete" ? "Deleting…" : "Delete permanently"}
          </button>
        </Dialog>
      )}
      {quality && (
        <Dialog label="Map quality" onClose={() => setQuality(null)}>
          <h2>Map quality</h2>
          <dl className="quality">
            <dt>LiDAR frames</dt>
            <dd>{quality.quality?.lidar_frames}</dd>
            <dt>Frames with pose</dt>
            <dd>{quality.quality?.lidar_pose_fraction == null ? "Unknown" : `${Math.round(quality.quality.lidar_pose_fraction * 100)}%`}</dd>
            <dt>Gaps over 1 s</dt>
            <dd>{quality.quality?.lidar_gaps_over_1s}</dd>
            <dt>Total space coverage</dt>
            <dd>No reference</dd>
            <dt>Absolute accuracy</dt>
            <dd>Not measured</dd>
          </dl>
          <p>These indicators describe the source data. Inspect geometry in Rerun before using the map for navigation. Segments from separate restarts require alignment.</p>
          <button autoFocus onClick={() => setQuality(null)}>
            Close
          </button>
        </Dialog>
      )}
    </>
  );
}
