import { Cloud, Check, ExternalLink, Pause, Upload } from "lucide-react";
import type { Item, State } from "./types";

type Action = (name: string, fn: () => Promise<unknown>) => Promise<void>;
type Api = (path: string, data?: unknown) => Promise<unknown>;
const gb = (bytes = 0) => (bytes / 1e9).toFixed(2);

export function CloudPanel({
  cloud,
  action,
  api,
  pending,
}: {
  cloud: State["cloud"];
  action: Action;
  api: Api;
  pending: boolean;
}) {
  if (!cloud) return null;
  return (
    <section className="cloud-panel" aria-label="DimOS Cloud">
      <div className="cloud-heading">
        <Cloud size={18} />
        <strong>DimOS Cloud</strong>
      </div>
      <p>
        {cloud.account?.email ||
          (cloud.configured
            ? "Account saved on this Mac"
            : "Back up your recordings to the cloud.")}
      </p>
      {cloud.login ? (
        <div role="status" className="cloud-login">
          <p>Approve this device in your browser:</p>
          <strong className="mono">{cloud.login.code}</strong>
          <a href={cloud.login.url} target="_blank" rel="noreferrer">
            Open sign-in <ExternalLink size={13} />
          </a>
          <small>
            Waiting for approval. This code expires in{" "}
            {Math.max(
              0,
              Math.ceil((cloud.login.expires_at - Date.now() / 1000) / 60),
            )}{" "}
            min.
          </small>
        </div>
      ) : (
        <div className="cloud-actions">
          <button
            disabled={pending || !!cloud.active_segment}
            onClick={() =>
              void action("cloud-login", () => api("/cloud/login"))
            }
          >
            {cloud.configured ? "Sign in again" : "Connect DimOS Cloud"}
          </button>
          {cloud.configured && (
            <button
              disabled={pending || !!cloud.active_segment}
              onClick={() =>
                void action("cloud-check", () => api("/cloud/refresh"))
              }
            >
              Check backups
            </button>
          )}
        </div>
      )}
      {cloud.quota && (
        <small>
          {gb(cloud.quota.used_total)} GB stored · {cloud.quota.pct}% of cloud
          quota
        </small>
      )}
      {cloud.error && (
        <p className="error-text" role="alert">
          {cloud.error}
        </p>
      )}
      <a href={cloud.console_url} target="_blank" rel="noreferrer">
        Cloud console <ExternalLink size={12} />
      </a>
      <small>
        Uploads include all recorded sensor streams. Local originals are kept.
      </small>
    </section>
  );
}

export function BackupControl({
  segment,
  cloud,
  action,
  api,
  pending,
}: {
  segment: Item;
  cloud: State["cloud"];
  action: Action;
  api: Api;
  pending: boolean;
}) {
  const b = segment.backup;
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
            disabled={
              pending ||
              !cloud?.configured ||
              !!cloud?.active_segment ||
              !!cloud?.login ||
              segment.status === "recording"
            }
            title={
              !cloud?.configured
                ? "Connect DimOS Cloud in the sidebar first"
                : segment.status === "recording"
                  ? "Save the recording first"
                  : "Upload all recorded streams"
            }
            onClick={() =>
              void action("cloud-upload", () =>
                api(`/cloud/uploads/${segment.id}`),
              )
            }
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
