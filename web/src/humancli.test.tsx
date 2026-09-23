// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { State } from "./types";

const stub = vi.hoisted(() => ({
  state: null as any,
  change: () => {},
  armed: (_v: boolean) => {},
  command: vi.fn(),
}));
vi.mock("./sdk", () => ({
  robot: {
    get onChange() {
      return stub.change;
    },
    set onChange(fn: () => void) {
      stub.change = fn;
    },
    get onArmed() {
      return stub.armed;
    },
    set onArmed(fn: (v: boolean) => void) {
      stub.armed = fn;
    },
    current: () => stub.state,
    start: async () => {},
    close: () => {},
    disarm: () => {},
    arm: () => {
      stub.armed(true);
    },
    keys: () => {},
    command: stub.command,
  },
}));
vi.mock("./MapCanvas", () => ({ MapCanvas: () => null }));
import { App } from "./main";
let root: Root;
let host: HTMLDivElement;
function button(name: string): HTMLButtonElement {
  const b = [...host.querySelectorAll("button")].find(
    (b) =>
      b.textContent?.trim() === name || b.getAttribute("aria-label") === name,
  );
  if (!b) throw Error(`Missing button: ${name}`);
  return b;
}
beforeEach(async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  stub.state = {
    dimos_sha: "test-sha",
    storage_root: "/test",
    connection: "online",
    mode: "teleop",
    epoch: 1,
    ip: "test",
    replay: true,
    telemetry: {},
    spaces: [],
    sessions: [],
    segments: [],
    maps: [],
    events: [],
    agent: {
      busy: false,
      messages: [],
      capabilities: [
        {
          name: "Stop movement",
          example: "stop",
          detail: "Pause the current navigation mission.",
        },
      ],
    },
  } as unknown as State;
  stub.command.mockImplementation(async (path, data) => {
    if (path === "/mode")
      stub.state = {
        ...stub.state,
        mode: data.mode,
        epoch: stub.state.epoch + 1,
      };
    return { ok: true, epoch: stub.state.epoch };
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<App />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it("keeps HumanCLI open after a safety pause and requires explicit re-enable", async () => {
  await act(async () => button("HumanCLI").click());
  expect(
    host.querySelector('[aria-label="HumanCLI instruction"]'),
  ).not.toBeNull();
  await act(async () => {
    stub.state = { ...stub.state, mode: "idle", epoch: 3 };
    stub.change();
  });
  expect(
    host.querySelector('[aria-label="HumanCLI instruction"]'),
  ).not.toBeNull();
  expect(button("Enable HumanCLI").disabled).toBe(false);
  expect(button("Send instruction").disabled).toBe(true);
  expect(host.querySelector('[aria-label="W: Move forward"]')).toBeNull();
});
it("does not show messages from days ago", async () => {
  stub.state.agent.messages = [
    { role: "assistant", text: "Old reply", ts: Date.now() / 1000 - 86400 },
    { role: "assistant", text: "Current reply", ts: Date.now() / 1000 },
  ];
  await act(async () => button("HumanCLI").click());
  expect(host.textContent).not.toContain("Old reply");
  expect(host.textContent).toContain("Current reply");
});
it("shows the skills tooltip on focus and dismisses it with Escape", async () => {
  await act(async () => button("HumanCLI").click());
  const info = button("HumanCLI skills and commands");
  await act(async () => info.focus());
  expect(document.querySelector('[role="tooltip"]')?.textContent).toContain(
    "Stop movement",
  );
  expect(info.getAttribute("aria-describedby")).toBe(
    document.querySelector('[role="tooltip"]')?.id,
  );
  await act(async () =>
    info.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
});

it("a delayed Teleop blur cannot release the new HumanCLI epoch", async () => {
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  const listeners = vi.spyOn(window, "addEventListener");
  await act(async () => button("Enable controls").click());
  const blur = listeners.mock.calls.find(([name]) => name === "blur")?.[1] as
    (() => void) | undefined;
  expect(blur).toBeDefined();
  await act(async () => button("HumanCLI").click());
  const epoch = stub.state.epoch;
  stub.command.mockClear();
  await act(async () => {
    blur!();
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(stub.command).not.toHaveBeenCalledWith("/release", { epoch });
  expect(stub.command).toHaveBeenCalledWith("/heartbeat", { epoch });
});
