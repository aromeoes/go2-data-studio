/**
 * DIMENSIONAL app: Onboarding → Log in or Stay Local → Connect your robot →
 * Start Session → Session. One robot connection per session.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ScanLine } from "lucide-react";
import { robot } from "../sdk";
import type { SetupCatalog, State } from "../types";
import { useControllerNavigation } from "../useControllerNavigation";
import { Connect } from "./Connect";
import { Library } from "./Library";
import { Login, Onboarding } from "./Onboarding";
import { Session } from "./Session";
import { StartSession } from "./StartSession";
import { get, Spinner, Toasts, useToasts } from "./ui";

type Screen = "onboarding" | "login" | "connect" | "library" | "setup" | "session";

export function App() {
  const [state, setState] = useState<State | null>(null);
  const [online, setOnline] = useState(true);
  const [screen, setScreen] = useState<Screen | null>(null);
  const [setup, setSetup] = useState<SetupCatalog | null>(null);
  const [spaceId, setSpaceId] = useState("");
  const { items, push } = useToasts();

  const refresh = useCallback(async () => {
    try {
      let value = robot.current();
      if (!value) {
        const response = await fetch("/api/state");
        if (!response.ok) throw Error();
        value = (await response.json()) as State;
        // HTTP state carries setup and the library; live telemetry comes over the SDK.
        value.telemetry = {};
      }
      setState(value);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    robot.onChange = () => void refresh();
    void robot.start().catch((e) => push(e.message, "error"));
    void refresh();
    const id = setInterval(refresh, 1000);
    return () => {
      clearInterval(id);
      robot.close();
    };
  }, []);

  // D-pad and A move through and press controls on every screen (Steam Deck).
  useControllerNavigation(() => true);

  const signedIn = !!state?.cloud?.configured;

  // First screen: resume a live connection, otherwise onboarding only when signed out.
  useEffect(() => {
    if (!state || screen) return;
    if (state.connection !== "offline") setScreen(state.profile?.preset === "base" ? "setup" : "session");
    else setScreen(signedIn ? "connect" : "onboarding");
  }, [state, screen]);

  // A connection that ends returns to the robot list.
  useEffect(() => {
    if (state?.connection === "offline" && (screen === "setup" || screen === "session")) setScreen("connect");
  }, [state?.connection]);

  // Saved robots and the module catalog for the setup and session headers.
  useEffect(() => {
    if (screen === "setup" || screen === "session")
      get<SetupCatalog>("/setup")
        .then(setSetup)
        .catch((e) => push(e.message, "error"));
  }, [screen]);

  // Default to the first space ("Starting space" on a new device).
  useEffect(() => {
    if (state && !state.spaces.some((s) => s.id === spaceId)) setSpaceId(state.spaces[0]?.id || "");
  }, [state?.spaces.length]);

  const wasSignedIn = useRef(signedIn);
  useEffect(() => {
    if (signedIn && !wasSignedIn.current) push(state?.cloud?.account?.email ? `Signed in as ${state.cloud.account.email}` : "Signed in to DimOS Cloud");
    wasSignedIn.current = signedIn;
    if (signedIn && screen === "login") setScreen("connect");
  }, [signedIn]);

  if (!state || !screen)
    return (
      <main className="screen centered">
        {online ? (
          <Spinner>Loading</Spinner>
        ) : (
          <section className="card onboarding">
            <ScanLine size={28} />
            <h1>The app is not responding</h1>
            <p className="hint">The local service stopped. Restart DIMENSIONAL.</p>
          </section>
        )}
      </main>
    );
  const kind = state.robot_kind === "vector" ? "vector" : "go2";
  const robotName = state.replay
    ? "Recording replay"
    : setup?.robots.find((r) => r.id === state.robot_id)?.name || (kind === "vector" ? "Vector" : "Go2");
  const catalog = setup?.sessions[kind];
  const blueprintName = catalog?.blueprints.find((b) => b.id === state.profile?.preset)?.name || "Session";
  return (
    <div className="flow" data-screen={screen}>
      {!online && (
        <p className="banner" role="alert">
          The local service is not responding. Motion control expires automatically.
        </p>
      )}
      {screen === "onboarding" && <Onboarding onLogin={() => setScreen("login")} onLocal={() => setScreen("connect")} />}
      {screen === "login" && <Login cloud={state.cloud} notify={push} onBack={() => setScreen("onboarding")} />}
      {screen === "connect" && (
        <Connect state={state} notify={push} onConnecting={() => setScreen("setup")} onLibrary={() => setScreen("library")} />
      )}
      {screen === "library" && (
        <Library
          state={state}
          spaceId={spaceId}
          onSpace={setSpaceId}
          notify={push}
          onBack={() => setScreen("connect")}
          onReplaying={() => setScreen("setup")}
        />
      )}
      {screen === "setup" &&
        (catalog ? (
          <StartSession
            key={`${state.robot_id}:${kind}:${state.replay}`}
            state={state}
            catalog={catalog}
            robotName={robotName}
            notify={push}
            onStarted={() => {
              // The SDK picks up the channels of the modules just added.
              robot.close();
              void robot.start().catch((e) => push(e.message, "error"));
              setScreen("session");
            }}
            onBack={() => setScreen("connect")}
          />
        ) : (
          <main className="screen centered">
            <Spinner>Loading modules</Spinner>
          </main>
        ))}
      {screen === "session" && (
        <Session
          state={state}
          robotName={robotName}
          blueprintName={blueprintName}
          spaceId={spaceId}
          onSpace={setSpaceId}
          notify={push}
          onEnded={() => setScreen("connect")}
        />
      )}
      <Toasts items={items} />
    </div>
  );
}
