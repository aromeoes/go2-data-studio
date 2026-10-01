// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SessionCatalog, State } from "../types";

const stub = vi.hoisted(() => ({
  state: null as any,
  change: () => {},
  command: vi.fn(),
  keys: vi.fn(),
  arm: vi.fn(),
  input: "keyboard",
}));
vi.mock("../sdk", () => ({
  robot: {
    get onChange() {
      return stub.change;
    },
    set onChange(fn: () => void) {
      stub.change = fn;
    },
    onArmed: () => {},
    current: () => stub.state,
    start: async () => {},
    close: () => {},
    disarm: () => {},
    arm: stub.arm,
    keys: stub.keys,
    gamepad: () => {},
    get inputSource() {
      return stub.input;
    },
    selectInput: (v: string) => {
      stub.input = v;
    },
    command: stub.command,
    camera: "",
    cameraFrames: 0,
    cameraBytes: 0,
    embodiment: "go2",
  },
}));
vi.mock("../MapCanvas", () => ({ MapCanvas: () => null }));
import { App } from "./App";

const required = ["GO2Connection", "ControlGate", "RelayBridgeModule"];
const teleopModules = [...required, "VoxelGridMapper", "CostMapper", "ConsoleBridge", "UnitreeSkillContainer"];
const mod = (id: string, extra: object = {}) => ({ id, icons: [], summary: `${id} summary`, official: true, capabilities: [], requires: [], ...extra });
const catalog: SessionCatalog = {
  modules: [
    ...required.map((id) => mod(id, { required: true })),
    mod("VoxelGridMapper"),
    mod("CostMapper", { requires: ["VoxelGridMapper"] }),
    mod("ConsoleBridge", { official: false }),
    mod("UnitreeSkillContainer"),
    mod("ReplanningAStarPlanner", { requires: ["CostMapper"] }),
    mod("McpClient"),
    mod("WavefrontFrontierExplorer", { requires: ["ReplanningAStarPlanner", "McpClient"] }),
  ],
  blueprints: [
    { id: "teleop", name: "Teleop", summary: "", recommended: true, locked: true, modules: teleopModules },
    { id: "custom", name: "Custom", summary: "", recommended: false, locked: false, modules: [] },
  ],
};
let requests: { url: string; body: any }[] = [];
let respond: (url: string, body: any) => { ok: boolean; json: unknown } = () => ({ ok: true, json: { ok: true } });
let root: Root;
let host: HTMLDivElement;

function button(name: string): HTMLButtonElement {
  const b = [...document.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === name || b.getAttribute("aria-label") === name,
  );
  if (!b) throw Error(`Missing button: ${name}`);
  return b;
}
const tick = (ms = 1000) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
const update = (changes: object) =>
  act(async () => {
    stub.state = { ...stub.state, ...changes };
    stub.change();
  });

function sessionState(): State {
  return {
    dimos_sha: "sha",
    storage_root: "/test",
    disk_free: 100e9,
    connection: "online",
    robot_id: "robot1",
    robot_kind: "go2",
    mode: "idle",
    epoch: 1,
    ip: "10.0.0.2",
    replay: false,
    profile: { preset: "custom", enabled: ["teleop", "camera", "lidar", "mapping", "recording", "navigation", "humancli"] },
    selected_modules: [...teleopModules, "ReplanningAStarPlanner", "McpClient"],
    loading_modules: false,
    hold: false,
    telemetry: {},
    cloud: { configured: true, account: { email: "a@b.c", id: "1" }, login: null, error: null, active_segment: null, console_url: "", quota: null },
    spaces: [{ id: "space1", name: "Office", created: 1, status: "ready", folder: "/test/office" }],
    sessions: [{ id: "session1", parent: "space1", source: "import", created: 1, status: "closed", folder: "/f" }],
    segments: [{ id: "segment1", parent: "session1", created: 1, status: "closed", path: "/test/raw.db", folder: "/f" }],
    maps: [],
    events: [],
    agent: { busy: false, messages: [], model: { configured: true, provider: "openai", model: "m", base_url: "", vision: false }, capabilities: [{ name: "Stop movement", example: "stop", detail: "Pause the current navigation mission." }] },
  } as unknown as State;
}

async function mount(state: State) {
  stub.state = state;
  await act(async () => root.render(<App />));
  await tick(0);
}

beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  requests = [];
  respond = () => ({ ok: true, json: { ok: true } });
  stub.input = "keyboard";
  stub.command.mockReset();
  stub.command.mockImplementation(async (path: string, data: any) => {
    if (path === "/mode") stub.state = { ...stub.state, mode: data.mode, epoch: stub.state.epoch + 1 };
    return { ok: true, epoch: stub.state.epoch };
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = String(url);
    if (path === "/api/setup")
      return { ok: true, json: async () => ({ robots: [{ id: "robot1", name: "My Go2", kind: "go2", ip: "10.0.0.2" }], sessions: { go2: catalog, vector: catalog } }) } as Response;
    if (path === "/api/state") return { ok: true, json: async () => structuredClone(stub.state) } as Response;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ url: path, body });
    const result = respond(path, body);
    return { ok: result.ok, json: async () => result.json } as Response;
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("shows onboarding only when signed out, and Stay Local goes to the robot list", async () => {
  const state = sessionState();
  await mount({ ...state, connection: "offline", cloud: { ...state.cloud!, configured: false, account: null } });
  expect(host.textContent).toContain("Log into Dimensional");
  await act(async () => button("Stay Local").click());
  expect(host.textContent).toContain("Robots available");
});

it("starts the chosen blueprint on the same connection", async () => {
  await mount({ ...sessionState(), profile: { preset: "base", enabled: ["teleop", "camera", "lidar"] }, selected_modules: required });
  expect(host.textContent).toContain("Select blueprint");
  await act(async () => button("Custom").click());
  const explorer = [...host.querySelectorAll(".modules li")].find((l) => l.textContent?.includes("WavefrontFrontierExplorer"))!;
  await act(async () => explorer.querySelector("input")!.click());
  expect(host.textContent).toContain("Also added: ReplanningAStarPlanner, McpClient");
  await act(async () => button("START").click());
  const start = requests.find((r) => r.url === "/api/session/modules")!;
  expect(start.body).toMatchObject({ robot_id: "robot1", preset: "custom" });
  expect(start.body.modules).toEqual(expect.arrayContaining(["WavefrontFrontierExplorer", "McpClient", ...required]));
  expect(requests.some((r) => r.url === "/api/disconnect" || r.url === "/api/connect")).toBe(false);
  await update({ profile: { preset: "custom", enabled: ["teleop"] }, loading_modules: false });
  expect(host.textContent).toContain("Record your exploration");
});

it("drives on W without an Enable step and hands control back when idle", async () => {
  await mount(sessionState());
  expect(host.textContent).not.toContain("Enable controls");
  await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW", key: "w" })));
  expect(stub.command).toHaveBeenCalledWith("/mode", { mode: "teleop" });
  expect(stub.arm).toHaveBeenCalled();
  expect(stub.keys).toHaveBeenLastCalledWith(new Set(["w"]));
  await act(async () => window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyW", key: "w" })));
  stub.command.mockClear();
  // Separate steps so the state refresh renders before the idle timer fires.
  await tick(1000);
  expect(stub.command).not.toHaveBeenCalledWith("/release", { epoch: 2 });
  await tick(1600);
  expect(stub.command).toHaveBeenCalledWith("/release", { epoch: 2 });
});

it("asks before taking control from a working HumanCLI", async () => {
  await mount({ ...sessionState(), mode: "agent", agent: { ...sessionState().agent, busy: true } });
  await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW", key: "w" })));
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("HumanCLI is controlling the robot");
  expect(stub.command).not.toHaveBeenCalledWith("/mode", { mode: "teleop" });
  await act(async () => button("Switch to Teleop").click());
  expect(stub.command).toHaveBeenCalledWith("/mode", { mode: "teleop" });
});

it("turns movement off with the toggle", async () => {
  await mount(sessionState());
  await act(async () => (host.querySelector('[role="switch"]') as HTMLInputElement).click());
  expect(requests).toContainEqual({ url: "/api/hold", body: { on: true } });
});

it("offers deletion only for non-backed-up segments and requires confirmation", async () => {
  await mount(sessionState());
  await act(async () => button("Delete segment segmen").click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("no confirmed backup");
  await act(async () => button("Cancel").click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(requests.some((r) => r.url.includes("/delete"))).toBe(false);
  await act(async () => button("Delete segment segmen").click());
  await act(async () => button("Delete permanently").click());
  expect(requests).toContainEqual({ url: "/api/segments/segment1/delete", body: { confirmed: true } });
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await update({ segments: [{ ...stub.state.segments[0], backup: { status: "complete" } }] });
  expect(host.querySelector('[aria-label="Delete segment segmen"]')).toBeNull();
});

it("disables deletion while a recording or map job uses the segment, and keeps the dialog on refusal", async () => {
  await mount(sessionState());
  await update({ segments: [{ ...stub.state.segments[0], status: "recording" }] });
  expect(button("Delete segment segmen").disabled).toBe(true);
  await update({ segments: [{ ...stub.state.segments[0], status: "closed" }], maps: [{ id: "map1", parent: "segment1", status: "running", created: 1, folder: "/m" }] });
  expect(button("Delete segment segmen").disabled).toBe(true);
  await update({ maps: [] });
  respond = () => ({ ok: false, json: { detail: "Pause the upload first" } });
  await act(async () => button("Delete segment segmen").click());
  await act(async () => button("Delete permanently").click());
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  expect(host.textContent).toContain("Pause the upload first");
});

it("renames a space from the sidebar without changing its identity", async () => {
  await mount(sessionState());
  await act(async () => button("Open menu").click());
  await act(async () => button("Rename Office").click());
  const input = document.querySelector('[aria-label="New space name"]') as HTMLInputElement;
  expect(input.value).toBe("Office");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "Upstairs");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Rename").click());
  expect(requests).toContainEqual({ url: "/api/spaces/space1/rename", body: { name: "Upstairs" } });
});

it("pauses control before generating a map", async () => {
  await mount({ ...sessionState(), mode: "agent" });
  await act(async () => button("Pause & generate map").click());
  expect(stub.command).toHaveBeenCalledWith("/mode", { mode: "idle" });
  expect(requests.find((r) => r.url === "/api/maps")?.body).toMatchObject({ segment_id: "segment1" });
});

it("hides HumanCLI messages from days ago and shows the skills tooltip on focus", async () => {
  const state = sessionState();
  state.agent.messages = [
    { role: "assistant", text: "Old reply", ts: Date.now() / 1000 - 86400 },
    { role: "assistant", text: "Current reply", ts: Date.now() / 1000 },
  ];
  await mount(state);
  await act(async () => button("HumanCLI").click());
  expect(host.textContent).not.toContain("Old reply");
  expect(host.textContent).toContain("Current reply");
  const info = button("HumanCLI skills and commands");
  await act(async () => info.focus());
  expect(document.querySelector('[role="tooltip"]')?.textContent).toContain("Stop movement");
  await act(async () => info.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
});

it("a delayed Teleop blur cannot release the new HumanCLI lease", async () => {
  await mount(sessionState());
  await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW", key: "w" })));
  await act(async () => window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyW", key: "w" })));
  await act(async () => button("HumanCLI").click());
  await tick(1000);
  const epoch = stub.state.epoch;
  stub.command.mockClear();
  await act(async () => window.dispatchEvent(new Event("blur")));
  await tick(300);
  expect(stub.command).not.toHaveBeenCalledWith("/release", { epoch });
  expect(stub.command).toHaveBeenCalledWith("/heartbeat", { epoch });
});
