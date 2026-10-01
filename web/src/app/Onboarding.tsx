/** Onboarding and Log into Dimensional. Shown on launch only when nobody is signed in. */
import { ArrowLeft } from "lucide-react";
import type { State } from "../types";
import { CloudCode, type Notify } from "./ui";

export function Onboarding({ onLogin, onLocal }: { onLogin: () => void; onLocal: () => void }) {
  return (
    <main className="screen centered">
      <section className="card onboarding">
        <div className="wordmark">DIMENSIONAL</div>
        <button className="choice primary" autoFocus onClick={onLogin}>
          <strong>Log into Dimensional</strong>
          <span>Complimentary hosting for your recordings and maps</span>
        </button>
        <button className="choice" onClick={onLocal}>
          Stay Local
        </button>
        <p className="hint">Stay Local keeps everything on this device. You can sign in later from the sidebar.</p>
      </section>
    </main>
  );
}

export function Login({ cloud, onBack, notify }: { cloud: State["cloud"]; onBack: () => void; notify: Notify }) {
  return (
    <main className="screen centered">
      <section className="card login">
        <button className="icon-button back" aria-label="Back" onClick={onBack}>
          <ArrowLeft size={18} />
        </button>
        <div className="wordmark">DIMENSIONAL</div>
        <CloudCode cloud={cloud} notify={notify} />
        <p className="hint">Scan with your phone or open the link, then approve this device. You stay signed in until you sign out.</p>
      </section>
    </main>
  );
}
