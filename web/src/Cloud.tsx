import { useEffect, useId, useRef, useState } from "react";
import { Check, Pause, Upload } from "lucide-react";
import type { Item, State } from "./types";

type Action = (name: string, fn: () => Promise<unknown>) => Promise<void>;
type Api = (path: string, data?: unknown) => Promise<unknown>;
const gb = (bytes = 0) => (bytes / 1e9).toFixed(2);

export function BackupControl({
  segment,
  spaceName,
  cloud,
  action,
  api,
  pending,
}: {
  segment: Item;
  spaceName?: string;
  cloud: State["cloud"];
  action: Action;
  api: Api;
  pending: boolean;
}) {
  const b = segment.backup;
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const nameId = useId();
  useEffect(() => {
    if (naming) dialog.current?.showModal();
    else if (dialog.current?.open) dialog.current.close();
  }, [naming]);
  const cannotUpload = pending || submitting || !cloud?.configured || !!cloud?.active_segment || !!cloud?.login || !["closed", "interrupted"].includes(segment.status);
  function chooseName() {
    const stamp = new Date(segment.created * 1000).toISOString().slice(0, 16).replace("T", " ").replace(":", "-");
    const prefix = (spaceName || "Go2 recording").replace(/[\x00-\x1f/\\<>:"|?*]/g, " ");
    setName(b?.name || `${prefix} ${stamp} ${segment.id.slice(0, 6)}`.slice(0, 120));
    setUploadError("");
    setNaming(true);
  }
  const active =
    !!b && ["preparing", "uploading", "verifying"].includes(b.status);
  const complete = b?.status === "complete";
  const percent = b?.percent || 0;
  const sameAccount = !cloud?.account || cloud.account.id === b?.owner_id;
  const label =
    b?.status === "preparing"
      ? "Preparing dataset"
      : b?.status === "verifying"
        ? "Verifying backup"
        : "Uploading";
  if (complete)
    return (
      <div className="backup-control">
        {b.name && <strong className="dataset-name">{b.name}</strong>}
        <span className="backup-done">
          <Check size={15} />
          Backed up
        </span>
        <small>
          {sameAccount
            ? "100% · Confirmed by Cloud"
            : "Backed up to another account"}
        </small>
        <small title={b.upload_id}>
          Verified{" "}
          {b.verified_at
            ? new Date(b.verified_at * 1000).toLocaleString("en-US")
            : "previously"}
        </small>
      </div>
    );
  return (
    <div className="backup-control">
      {b?.name && <strong className="dataset-name">{b.name}</strong>}
      {naming && <dialog
        ref={dialog}
        className="dialog upload-dialog"
        aria-labelledby={`${nameId}-title`}
        onCancel={() => setNaming(false)}
        onClose={() => setNaming(false)}
      >
        <form onSubmit={(event) => {
          event.preventDefault();
          if (cannotUpload || !name.trim()) return;
          setSubmitting(true);
          setUploadError("");
          void action("cloud-upload", async () => {
            try {
              await api(`/cloud/uploads/${segment.id}`, { name: name.trim() });
              setNaming(false);
            } catch (error) {
              setUploadError(error instanceof Error ? error.message : "Could not start upload. Try again.");
            }
          }).finally(() => setSubmitting(false));
        }}>
          <h2 id={`${nameId}-title`}>Upload dataset</h2>
          <label htmlFor={nameId}>Dataset name</label>
          <input id={nameId} autoFocus required maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder="Office, west wing" disabled={submitting} />
          <p>Upload this recording segment with all recorded streams. Local files keep their original names.</p>
          {uploadError && <p role="alert">{uploadError}</p>}
          <div className="setup-actions">
            <button type="button" disabled={submitting} onClick={() => setNaming(false)}>Cancel</button>
            <button type="submit" className="primary" disabled={cannotUpload || !name.trim()}>{submitting ? "Starting…" : "Start upload"}</button>
          </div>
        </form>
      </dialog>}
      {active ? (
        <>
          <span role="status">
            {label} · {percent}%
          </span>
          <progress
            aria-label={`Dataset upload: ${percent}%`}
            max={100}
            value={percent}
          />
          <small>
            {gb(b.uploaded_bytes)} / {gb(b.size)} GB
          </small>
          <button
            disabled={pending}
            onClick={() =>
              void action("cloud-pause", () =>
                api(`/cloud/uploads/${segment.id}/pause`),
              )
            }
          >
            <Pause size={12} />
            Pause upload
          </button>
        </>
      ) : (
        <>
          <button
            disabled={cannotUpload}
            title={
              !cloud?.configured
                ? "Connect DimOS Cloud in the sidebar first"
                : segment.status === "recording"
                  ? "Save the recording first"
                  : "Upload all recorded streams"
            }
            onClick={() => {
              if (b?.upload_id) void action("cloud-upload", () => api(`/cloud/uploads/${segment.id}`));
              else chooseName();
            }}
          >
            <Upload size={14} />
            {b?.status === "paused" || b?.status === "failed"
              ? "Resume upload"
              : "Upload dataset"}
          </button>
          {b?.status === "paused" && <small>Paused · {percent}%</small>}
          {b?.error && (
            <small className="error-text" role="alert">
              {b.error}
            </small>
          )}
        </>
      )}
    </div>
  );
}
