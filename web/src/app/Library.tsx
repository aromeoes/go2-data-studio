/** Recordings without a robot: browse spaces, upload, generate maps, import, replay. */
import { useState } from "react";
import { ArrowLeft, Map as MapIcon } from "lucide-react";
import type { State } from "../types";
import { Archive } from "./Archive";
import { api, CloudCode, gb, type Notify } from "./ui";

export function Library({
  state,
  spaceId,
  onSpace,
  notify,
  onBack,
  onReplaying,
}: {
  state: State;
  spaceId: string;
  onSpace: (id: string) => void;
  notify: Notify;
  onBack: () => void;
  onReplaying: () => void;
}) {
  const [signingIn, setSigningIn] = useState(false);
  const cloud = state.cloud;
  return (
    <main className="screen">
      <header className="bar">
        <button className="link" onClick={onBack}>
          <ArrowLeft size={16} /> Robots
        </button>
        <span className="wordmark small">DIMENSIONAL</span>
        <span className="muted">Local storage: {gb(state.disk_free)} GB free</span>
      </header>
      <section className="card library">
        <div className="row">
          <h1>Recordings</h1>
          <span className="spacer" />
          {cloud?.configured ? (
            <span className="muted">DimOS Cloud: {cloud.account?.email || "signed in"}</span>
          ) : (
            !signingIn && (
              <button className="primary" onClick={() => setSigningIn(true)}>
                Sign in to DimOS Cloud to upload
              </button>
            )
          )}
        </div>
        {signingIn && !cloud?.configured && <CloudCode cloud={cloud} notify={notify} />}
        <nav className="spaces row" aria-label="Spaces">
          {state.spaces.map((s) => (
            <button key={s.id} aria-pressed={s.id === spaceId} onClick={() => onSpace(s.id)}>
              <MapIcon size={16} /> {s.name}
            </button>
          ))}
        </nav>
      </section>
      <Archive
        state={state}
        spaceId={spaceId}
        notify={notify}
        onReplay={(segment) =>
          api("/connect", { segment_id: segment.id })
            .then(onReplaying)
            .catch((e) => notify(e.message, "error"))
        }
      />
    </main>
  );
}
