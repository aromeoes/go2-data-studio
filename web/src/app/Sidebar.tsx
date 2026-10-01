/** Session sidebar: spaces, DimOS Cloud account, local storage. Opens from the menu button. */
import { useState } from "react";
import { ExternalLink, Map as MapIcon, Pencil, Plus, X } from "lucide-react";
import type { State } from "../types";
import { api, CloudCode, gb, type Notify } from "./ui";

export function Sidebar({
  state,
  spaceId,
  onSpace,
  notify,
  onClose,
}: {
  state: State;
  spaceId: string;
  onSpace: (id: string) => void;
  notify: Notify;
  onClose: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const cloud = state.cloud;
  return (
    <div className="overlay drawer-overlay" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        className="drawer"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="row">
          <span className="wordmark small">DIMENSIONAL</span>
          <button className="icon-button" aria-label="Close menu" autoFocus onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <h2>Spaces</h2>
        <nav className="spaces">
          {state.spaces.map((s) =>
            renaming === s.id ? (
              <form
                key={s.id}
                className="row"
                onSubmit={(e) => {
                  e.preventDefault();
                  api(`/spaces/${s.id}/rename`, { name: newName })
                    .then(() => setRenaming(null))
                    .catch((err) => notify(err.message, "error"));
                }}
              >
                <input aria-label="New space name" autoFocus required maxLength={80} value={newName} onChange={(e) => setNewName(e.target.value)} />
                <button className="primary">Rename</button>
              </form>
            ) : (
              <div key={s.id} className="space-row">
                <button aria-pressed={s.id === spaceId} disabled={!!state.session && s.id !== spaceId} onClick={() => onSpace(s.id)}>
                  <MapIcon size={16} /> {s.name}
                </button>
                <button
                  className="icon-button"
                  aria-label={`Rename ${s.name}`}
                  onClick={() => {
                    setRenaming(s.id);
                    setNewName(s.name || "");
                  }}
                >
                  <Pencil size={14} />
                </button>
              </div>
            ),
          )}
        </nav>
        {state.session && <p className="hint">Save the recording to change spaces.</p>}
        {adding ? (
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              api("/spaces", { name })
                .then((space) => {
                  onSpace(space.id);
                  setAdding(false);
                  setName("");
                })
                .catch((err) => notify(err.message, "error"));
            }}
          >
            <input aria-label="Space name" autoFocus required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="Office, west wing" />
            <button className="primary">Create</button>
          </form>
        ) : (
          <button onClick={() => setAdding(true)}>
            <Plus size={16} /> New space
          </button>
        )}

        <h2>DimOS Cloud</h2>
        {cloud?.account ? (
          <>
            <button className="account" aria-expanded={accountOpen} onClick={() => setAccountOpen(!accountOpen)}>
              {cloud.account.email}
            </button>
            {accountOpen && (
              <button
                onClick={() =>
                  api("/cloud/signout")
                    .then(() => notify("Signed out of DimOS Cloud"))
                    .catch((err) => notify(err.message, "error"))
                }
              >
                Sign out
              </button>
            )}
            {cloud.quota && (
              <p className="muted">
                {gb(cloud.quota.used_total)} GB stored · {cloud.quota.pct}% of cloud quota
              </p>
            )}
            <a href={cloud.console_url} target="_blank" rel="noreferrer">
              Cloud console <ExternalLink size={13} />
            </a>
          </>
        ) : signingIn ? (
          <CloudCode cloud={cloud} notify={notify} />
        ) : (
          <button className="primary" onClick={() => setSigningIn(true)}>
            Sign in to DimOS Cloud
          </button>
        )}

        <div className="drawer-bottom">
          <h2>Local storage</h2>
          <strong>{gb(state.disk_free)} GB free</strong>
          <code>{state.storage_root}</code>
        </div>
      </aside>
    </div>
  );
}
