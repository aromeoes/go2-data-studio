/**
 * UX flow prototype entry (flow.html). Same simulated backend as mock mode,
 * new screens. Never part of the production build.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../mock/mock.css";
import "@fontsource-variable/inter";
import "./flow.css";
import "./flow-theme.css";
import { DEFAULT_SCENARIO, MockBackend, type Scenario } from "../mock/backend";
import { installFetch, installRobot, startLoops } from "../mock/install";
import { mountPanel } from "../mock/Panel";
import { App } from "./App";

const KEY = "dimensional-mock-scenario";

function load(): Scenario {
  try {
    return { ...DEFAULT_SCENARIO, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return DEFAULT_SCENARIO;
  }
}

const backend = new MockBackend(load());
installFetch(backend);
installRobot(backend);
startLoops(backend);
Object.assign(window, { mock: backend });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
mountPanel(backend, (scenario) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(scenario));
  } catch {
    // Private windows can refuse storage. The scenario then lasts until reload.
  }
});
