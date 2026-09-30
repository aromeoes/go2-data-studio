/** Swaps the app's two outside channels (HTTP and the DimOS SDK session) for the mock backend. */
import { robot } from "../sdk";
import type { Motion } from "../gamepad";
import type { MockBackend } from "./backend";
import { drawCamera } from "./world";

/** Answers same-origin /api requests from the mock. Everything else uses the real fetch. */
export function installFetch(backend: MockBackend) {
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const href =
      typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(href, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/"))
      return real(input, init);
    let body: unknown;
    try {
      body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    } catch {
      body = undefined;
    }
    const result = await backend.http(init?.method || "GET", url.pathname.slice(4), body);
    return new Response(JSON.stringify(result.json), {
      status: result.status,
      headers: { "Content-Type": "application/json" },
    });
  };
}

/**
 * Replaces the behavior of the shared RobotSDK instance. The app keeps importing
 * the same object, so none of its code changes. Input selection stays real, which
 * means a physical gamepad drives the simulated robot.
 */
export function installRobot(backend: MockBackend) {
  const sdk = robot as any;
  let armed = false;
  let linear = 0.5;
  const halt = () => {
    const was = armed;
    armed = false;
    sdk.analog.reset();
    sdk.analogHeld = false;
    backend.setVelocity(0, 0, 0);
    if (was) sdk.onArmed(false);
  };
  Object.defineProperty(sdk, "ready", {
    configurable: true,
    get: () => backend.connection === "online",
    set: () => {},
  });
  Object.assign(sdk, {
    start: async () => {},
    close: halt,
    disarm: halt,
    machine: { estop: halt },
    current: () => backend.live(),
    command: (path: string, body: unknown) => backend.command(path, body),
    arm(speed: number) {
      if (backend.connection !== "online") throw Error("DimOS SDK is disconnected");
      linear = speed;
      armed = true;
      sdk.onArmed(true);
    },
    keys(pressed: Set<string>) {
      if (sdk.analog.selected || !armed) return;
      const vector = sdk.embodiment === "vector";
      const on = (...keys: string[]) => (keys.some((k) => pressed.has(k)) ? 1 : 0);
      backend.setVelocity(
        (on("w", "ArrowUp") - on("s", "ArrowDown")) * linear,
        vector ? 0 : (on("q") - on("e")) * Math.min(linear, 0.2),
        (on("a", "ArrowLeft") - on("d", "ArrowRight")) * (vector ? 1.5 : 0.5),
      );
    },
    gamepad(value: Motion) {
      if (!sdk.analog.selected || !armed) return;
      backend.setVelocity(value.vx, sdk.embodiment === "vector" ? 0 : value.vy, value.wz);
    },
  });
  backend.onLeaveTeleop = halt;
  backend.onReset = halt;
}

/** Runs the simulation clock and renders camera frames while the robot is online. */
export function startLoops(backend: MockBackend) {
  const sdk = robot as any;
  const canvas = document.createElement("canvas");
  canvas.width = 480;
  canvas.height = 270;
  const ctx = canvas.getContext("2d");
  const setCamera = (url: string) => {
    if (sdk.camera) URL.revokeObjectURL(sdk.camera);
    sdk.camera = url;
  };
  let connection = backend.connection;
  let beat = 0;
  setInterval(() => {
    backend.tick();
    const online = backend.connection === "online";
    const changed = backend.connection !== connection;
    connection = backend.connection;
    if (!online && sdk.camera) setCamera("");
    if (++beat % 2 && !changed) return;
    if (online && ctx && !backend.frozen && backend.profile.enabled.includes("camera")) {
      drawCamera(ctx, backend.pose);
      canvas.toBlob((blob) => blob && backend.connection === "online" && setCamera(URL.createObjectURL(blob)), "image/jpeg", 0.7);
    }
    if (online || changed) sdk.onChange();
  }, 100);
}
