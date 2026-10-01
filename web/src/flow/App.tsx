/**
 * UX flow prototype: Onboarding → Log in or Stay Local → Connect your robot →
 * Start Session → Session. Wireframe level. Runs against the mock backend.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { robot } from "../sdk";
import type { State } from "../types";
import type { SavedRobot, SetupCatalog } from "../SessionSetup";
import { useControllerNavigation } from "../useControllerNavigation";
import { Connect } from "./Connect";
import { Login, Onboarding } from "./Onboarding";
import { Session } from "./Session";
import { StartSession } from "./StartSession";
import { get, Spinner, Toasts, useToasts } from "./ui";

type Screen = "onboarding" | "login" | "connect" | "setup" | "session";

export function App() {
  const [state, setState] = useState<State | null>(null);
  const [screen, setScreen] = useState<Screen | null>(null);
  const [robots, setRobots] = useState<SavedRobot[]>([]);
  const [spaceId, setSpaceId] = useState("");
  const { items, push } = useToasts();

  const refresh = useCallback(async () => {
    try {
      let value = robot.current();
      if (!value) {
        const response = await fetch("/api/state");
        value = (await response.json()) as State;
        value.telemetry = {};
      }
      setState(value);
    } catch {
      // The next poll retries.
    }
  }, []);

  useEffect(() => {
    robot.onChange = () => void refresh();
    void robot.start().catch(() => {});
    void refresh();
    const id = setInterval(refresh, 500);
    return () => {
      clearInterval(id);
      robot.close();
    };
  }, []);

  // D-pad and A move through and press controls on every screen (Steam Deck).
  useControllerNavigation(() => true);

  // First screen: resume a live connection, otherwise onboarding only when signed out.
  useEffect(() => {
    if (!state || screen) return;
    if (state.connection !== "offline") setScreen(state.profile?.preset === "base" ? "setup" : "session");
    else setScreen(state.cloud?.account ? "connect" : "onboarding");
  }, [state, screen]);

  // A connection that ends unexpectedly returns to the robot list.
  useEffect(() => {
    if (state?.connection === "offline" && (screen === "setup" || screen === "session")) setScreen("connect");
  }, [state?.connection]);

  // Saved robot names for the headers.
  useEffect(() => {
    if (screen === "setup" || screen === "session")
      get<SetupCatalog>("/setup")
        .then((c) => setRobots(c.robots))
        .catch(() => {});
  }, [screen]);

  // Default to the first space ("Starting space" on a new device).
  useEffect(() => {
    if (state && !state.spaces.some((s) => s.id === spaceId)) setSpaceId(state.spaces[0]?.id || "");
  }, [state?.spaces.length]);

  const account = state?.cloud?.account?.email;
  const signedIn = useRef(account);
  useEffect(() => {
    if (account && !signedIn.current) push(`Signed in as ${account}`);
    signedIn.current = account;
    if (account && screen === "login") setScreen("connect");
  }, [account]);

  if (!state || !screen)
    return (
      <main className="screen centered">
        <Spinner>Loading</Spinner>
      </main>
    );
  const robotName = robots.find((r) => r.id === state.robot_id)?.name || (state.robot_kind === "vector" ? "Vector" : "Go2");
  return (
    <div className="flow" data-screen={screen}>
      {screen === "onboarding" && <Onboarding onLogin={() => setScreen("login")} onLocal={() => setScreen("connect")} />}
      {screen === "login" && <Login cloud={state.cloud} notify={push} onBack={() => setScreen("onboarding")} />}
      {screen === "connect" && <Connect state={state} notify={push} onConnecting={() => setScreen("setup")} />}
      {screen === "setup" && (
        <StartSession state={state} robotName={robotName} notify={push} onStarted={() => setScreen("session")} onBack={() => setScreen("connect")} />
      )}
      {screen === "session" && (
        <Session state={state} robotName={robotName} spaceId={spaceId} onSpace={setSpaceId} notify={push} onEnded={() => setScreen("connect")} />
      )}
      <Toasts items={items} />
    </div>
  );
}
