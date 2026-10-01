import { expect, it } from "vitest";
import { DEFAULT_SCENARIO, MockBackend } from "../mock/backend";
import { baseProfile, capabilitiesOf, embodiment, requiredModules, toggleModule } from "./modules";

const go2 = embodiment("go2");
const vector = embodiment("vector");

it("keeps required modules and pulls in dependencies", () => {
  const teleop = go2.blueprints[0].modules;
  const withExplore = toggleModule(teleop, "WavefrontFrontierExplorer", true, go2.modules);
  expect(withExplore).toEqual(expect.arrayContaining(["WavefrontFrontierExplorer", "ReplanningAStarPlanner", "McpClient"]));
  const withoutAgent = toggleModule(withExplore, "McpClient", false, go2.modules);
  expect(withoutAgent).not.toContain("WavefrontFrontierExplorer");
  expect(toggleModule(teleop, "GO2Connection", false, go2.modules)).toContain("GO2Connection");
});

it("keeps HumanCLI out of the Teleop blueprint and LiDAR modules off Vector", () => {
  expect(go2.blueprints[0]).toMatchObject({ locked: true, recommended: true });
  expect(go2.blueprints[0].modules).not.toContain("McpClient");
  expect(vector.modules.find((m) => m.id === "VoxelGridMapper")?.unavailable).toMatch(/LiDAR/);
  expect(toggleModule(vector.blueprints[0].modules, "VoxelGridMapper", true, vector.modules)).not.toContain("VoxelGridMapper");
  expect(capabilitiesOf(go2.blueprints[0].modules, go2.modules)).toEqual(
    expect.arrayContaining(["teleop", "camera", "lidar", "mapping", "recording"]),
  );
});

it("connects once with base modules, then adds the blueprint without reconnecting", async () => {
  let now = 1_000_000;
  const backend = new MockBackend({ ...DEFAULT_SCENARIO }, () => now);
  backend.latency = 0;
  const run = (seconds: number) => {
    for (let t = 0; t < seconds; t += 0.1) {
      now += 0.1;
      backend.tick();
    }
  };
  const post = async (path: string, body?: unknown) => {
    const result = await backend.http("POST", path, body);
    if (result.status !== 200) throw Error((result.json as { detail: string }).detail);
    return result.json as any;
  };
  await post("/connect", { robot_id: "robot-go2", profile: baseProfile("go2") });
  run(5);
  expect(backend.snapshot()).toMatchObject({ connection: "online", profile: { preset: "base" } });
  const modules = toggleModule(go2.blueprints[0].modules, "WavefrontFrontierExplorer", true, go2.modules);
  await post("/session/modules", { robot_id: "robot-go2", preset: "custom", modules, enabled: capabilitiesOf(modules, go2.modules) });
  expect(backend.snapshot()).toMatchObject({ connection: "online", loading_modules: true });
  run(3);
  expect(backend.snapshot()).toMatchObject({ connection: "online", loading_modules: false, selected_modules: modules });
  expect(requiredModules("go2").every((id) => modules.includes(id))).toBe(true);

  // HumanCLI exploration drives the robot; the movement toggle holds it in place.
  const { epoch } = await post("/mode", { mode: "agent" });
  await post("/agent", { text: "Explore this room", epoch, space_id: "space-office" });
  const keepAlive = () => void post("/heartbeat", { epoch: backend.epoch });
  for (let i = 0; i < 40; i++) {
    keepAlive();
    run(0.2);
  }
  expect(backend.snapshot().telemetry.skills?.active).toBe("begin_exploration");
  await post("/hold", { on: true });
  const held = { ...backend.pose };
  run(1);
  expect(backend.pose).toEqual(held);

  await post("/cloud/signout");
  expect(backend.snapshot().cloud?.account).toBeNull();
});
