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
    replay: false,
    telemetry: {},
    spaces: [{ id: "space1", name: "Office", created: 1 }],
    sessions: [
      { id: "session1", parent: "space1", source: "import", created: 1 },
    ],
    segments: [
      {
        id: "segment1",
        parent: "session1",
        created: 1,
        status: "closed",
        path: "/test/raw.db",
      },
    ],
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

it("offers deletion only for non-backed-up segments and requires confirmation", async () => {
  const request = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    } as Response);
  await act(async () => button("Delete segment segmen").click());
  expect(host.querySelector('[role="alertdialog"]')?.textContent).toContain(
    "no confirmed backup",
  );
  expect(request).not.toHaveBeenCalled();
  await act(async () => button("Cancel").click());
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
  expect(request).not.toHaveBeenCalled();
  await act(async () => button("Delete segment segmen").click());
  await act(async () => button("Delete permanently").click());
  expect(request).toHaveBeenCalledWith(
    "/api/segments/segment1/delete",
    expect.objectContaining({ body: JSON.stringify({ confirmed: true }) }),
  );
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
  await act(async () => {
    stub.state.segments[0].backup = { status: "complete" };
    stub.change();
  });
  expect(host.querySelector('[aria-label="Delete segment segmen"]')).toBeNull();
});

it("disables deletion while a recording or map job uses the segment", async () => {
  await act(async () => {
    stub.state.segments[0].status = "recording";
    stub.change();
  });
  expect(button("Delete segment segmen").disabled).toBe(true);
  await act(async () => {
    stub.state.segments[0].status = "closed";
    stub.state.maps = [{ id: "map1", parent: "segment1", status: "running" }];
    stub.change();
  });
  expect(button("Delete segment segmen").disabled).toBe(true);
});

it("keeps the confirmation open when server refuses deletion", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "Pause the upload first" }),
  } as Response);
  await act(async () => button("Delete segment segmen").click());
  await act(async () => button("Delete permanently").click());
  expect(host.querySelector('[role="alertdialog"]')?.textContent).toContain(
    "Pause the upload first",
  );
});

it("renames the selected space without changing its identity", async () => {
  const request = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_url, init) => {
      stub.state.spaces[0].name = JSON.parse(init?.body as string).name;
      return { ok: true, json: async () => stub.state.spaces[0] } as Response;
    });
  await act(async () => button("Rename space").click());
  const input = host.querySelector('[role="dialog"] input') as HTMLInputElement;
  expect(input.value).toBe("Office");
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Upstairs");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Save name").click());
  expect(request).toHaveBeenCalledWith(
    "/api/spaces/space1/rename",
    expect.objectContaining({ body: JSON.stringify({ name: "Upstairs" }) }),
  );
  expect(host.querySelector("h1")?.textContent).toContain("Upstairs");
});
