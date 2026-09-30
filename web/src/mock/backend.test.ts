import { expect, it } from "vitest";
import { DEFAULT_SCENARIO, MockBackend, type Scenario } from "./backend";

function setup(scenario: Partial<Scenario> = {}) {
  let now = 1_000_000;
  const backend = new MockBackend({ ...DEFAULT_SCENARIO, ...scenario }, () => now);
  backend.latency = 0;
  /** Advances simulated time in 0.1 s steps, keeping any control lease alive. */
  const run = (seconds: number) => {
    for (let t = 0; t < seconds; t += 0.1) {
      now += 0.1;
      if (backend.mode !== "idle") void backend.command("/heartbeat", { epoch: backend.epoch });
      backend.tick();
    }
  };
  const post = async (path: string, body?: unknown) => {
    const result = await backend.http("POST", path, body);
    if (result.status !== 200) throw Error((result.json as { detail: string }).detail);
    return result.json as any;
  };
  return { backend, run, post };
}

const FULL = DEFAULT_SCENARIO;

it("connects a saved Go2 for a signed-in user, then starts a full session", async () => {
  const { backend, run, post } = setup();
  expect(backend.snapshot().cloud?.account?.email).toBeTruthy();
  await post("/connect", { robot_id: "robot-go2" });
  expect(backend.snapshot().connection).toBe("connecting");
  expect(backend.live()).toBeNull();
  run(FULL.connectSeconds + 0.5);
  expect(backend.snapshot().connection).toBe("online");
  expect(backend.snapshot().profile?.preset).toBe("preview");
  const assistant = (await post("/setup")).presets[1];
  await post("/session/profile", { robot_id: "robot-go2", preset: assistant.id, enabled: assistant.enabled });
  expect(backend.snapshot().connection).toBe("connecting");
  run(FULL.sessionSeconds + 1);
  const state = backend.live()!;
  expect(state.profile?.preset).toBe("assistant");
  expect(state.telemetry.map?.known_m2).toBeGreaterThan(1);
  expect(state.telemetry.sensors?.lidar).toBeTruthy();
});

it("keeps retrying an unreachable robot and recovers when it appears", async () => {
  const { backend, run, post } = setup({ network: "none" });
  await post("/connect", { robot_id: "robot-go2" });
  run(FULL.connectSeconds + 1);
  expect(backend.snapshot().connection).toBe("reconnecting");
  expect(backend.snapshot().error).toContain("not responding at 10.15.9.58");
  backend.setScenario({ network: "go2" });
  run(0.3);
  expect(backend.snapshot().connection).toBe("online");
});

it("drives in Teleop, records, and stops on Emergency stop", async () => {
  const { backend, run, post } = setup();
  await post("/connect", { robot_id: "robot-go2" });
  run(5);
  await post("/session/profile", { robot_id: "robot-go2", preset: "map-record", enabled: ["teleop", "camera", "lidar", "mapping", "recording"] });
  run(5);
  await expect(post("/mode", { mode: "explore" })).rejects.toThrow("disabled in this session");
  await post("/record/start", { space_id: "space-office" });
  const { epoch } = await post("/mode", { mode: "teleop" });
  const start = { ...backend.pose };
  backend.setVelocity(0.5, 0, 0);
  run(2);
  expect(Math.hypot(backend.pose.x - start.x, backend.pose.y - start.y)).toBeGreaterThan(0.8);
  await post("/stop");
  const stopped = { ...backend.pose };
  run(1);
  expect(backend.pose).toEqual(stopped);
  expect(backend.snapshot().epoch).toBeGreaterThan(epoch);
  expect(backend.live()!.telemetry.control?.estop).toBe(true);
  await post("/record/stop");
  const segment = backend.snapshot().segments[0];
  expect(segment.status).toBe("closed");
  expect(segment.stats!.physical_bytes).toBeGreaterThan(1e6);
});

it("explores, tags a place and returns to it through HumanCLI", async () => {
  const { backend, run, post } = setup();
  await post("/connect", { robot_id: "robot-go2" });
  run(5);
  const assistant = (await post("/setup")).presets[1];
  await post("/session/profile", { robot_id: "robot-go2", preset: assistant.id, enabled: assistant.enabled });
  run(5);
  let mode = await post("/mode", { mode: "agent" });
  await post("/agent", { text: "Remember this as reception", epoch: mode.epoch, space_id: "space-office" });
  run(2);
  const home = { ...backend.pose };
  mode = await post("/mode", { mode: "explore" });
  run(20);
  expect(Math.hypot(backend.pose.x - home.x, backend.pose.y - home.y)).toBeGreaterThan(1);
  mode = await post("/mode", { mode: "agent" });
  await post("/agent", { text: "Go to reception", epoch: mode.epoch, space_id: "space-office" });
  run(40);
  expect(Math.hypot(backend.pose.x - home.x, backend.pose.y - home.y)).toBeLessThan(0.4);
  expect(backend.snapshot().agent.messages.at(-1)?.text).toBe("Arrived at reception.");
});

it("uploads a named dataset, fails once on request, and completes on resume", async () => {
  const { backend, run, post } = setup();
  backend.failNextUpload = true;
  await post("/cloud/uploads/a41c9e77", { name: "Office west wing" });
  run(12);
  let backup = backend.snapshot().segments.find((s) => s.id === "a41c9e77")!.backup!;
  expect(backup.status).toBe("failed");
  expect(backup.percent).toBeGreaterThanOrEqual(60);
  await post("/cloud/uploads/a41c9e77");
  run(12);
  backup = backend.snapshot().segments.find((s) => s.id === "a41c9e77")!.backup!;
  expect(backup).toMatchObject({ status: "complete", name: "Office west wing", percent: 100 });
});

it("requires a cloud account before uploading", async () => {
  const { post } = setup({ account: "signed-out" });
  await expect(post("/cloud/uploads/a41c9e77", { name: "x" })).rejects.toThrow("Connect DimOS Cloud");
});
