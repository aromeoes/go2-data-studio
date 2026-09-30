/**
 * Mock mode entry (mock.html). Installs the simulated backend before the real app
 * loads, so the production UI runs unchanged with no robot, backend or cloud.
 * The production build (index.html) never imports this folder.
 */
import "./mock.css";
import { DEFAULT_SCENARIO, MockBackend, type Scenario } from "./backend";
import { installFetch, installRobot, startLoops } from "./install";
import { mountPanel } from "./Panel";

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
// Handy in the browser console: mock.dropConnection(), mock.snapshot(), ...
Object.assign(window, { mock: backend });

void import("../main").then(() =>
  mountPanel(backend, (scenario) => {
    try {
      localStorage.setItem(KEY, JSON.stringify(scenario));
    } catch {
      // Private windows can refuse storage. The scenario then lasts until reload.
    }
  }),
);
