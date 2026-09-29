// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import {
  SessionSetup,
  toggleCapability,
  type SetupCatalog,
} from "./SessionSetup";
import type { State } from "./types";
const capabilities = [
  {
    id: "lidar",
    name: "LiDAR",
    requires: [],
    detail: "",
    modules: ["Connection"],
  },
  {
    id: "mapping",
    name: "Mapping",
    requires: ["lidar"],
    detail: "",
    modules: ["Mapper"],
  },
  {
    id: "navigation",
    name: "Navigation",
    requires: ["mapping"],
    detail: "",
    modules: ["Planner"],
  },
  {
    id: "exploration",
    name: "Exploration",
    requires: ["navigation"],
    detail: "",
    modules: ["Explorer"],
  },
];
const catalog: SetupCatalog = {
  robots: [
    {
      id: "go2",
      name: "My Go2",
      kind: "go2",
      ip: "192.168.1.73",
      serial: "",
      profile: { preset: "map-record", enabled: capabilities.map((c) => c.id) },
    },
  ],
  capabilities,
  required_modules: ["ControlGate"],
  presets: [
    {
      id: "map-record",
      name: "Teleop + Recording",
      description: "Map",
      enabled: ["lidar", "mapping"],
    },
    {
      id: "assistant",
      name: "Full mode agent",
      description: "All capabilities",
      enabled: capabilities.map((c) => c.id),
    },
  ],
};
afterEach(() => vi.restoreAllMocks());
it("includes prerequisites and removes transitive dependents", () => {
  expect(toggleCapability([], "exploration", true, capabilities)).toEqual([
    "lidar",
    "mapping",
    "navigation",
    "exploration",
  ]);
  expect(
    toggleCapability(
      capabilities.map((c) => c.id),
      "mapping",
      false,
      capabilities,
    ),
  ).toEqual(["lidar"]);
});
it("connects saved hardware without starting a session or moving", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => catalog,
  } as Response);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const api = vi.fn(async () => ({}));
  await act(async () =>
    root.render(
      <SessionSetup
        state={
          {
            connection: "offline",
            mode: "idle",
            profile: { preset: "legacy", enabled: [] },
          } as unknown as State
        }
        api={api}
        refresh={async () => {}}
        pause={async () => {}}
        onApplied={() => {}}
      />,
    ),
  );
  const connect = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Connect My Go2"),
  )!;
  await act(async () => connect.click());
  expect(api).toHaveBeenCalledExactlyOnceWith("/connect", { robot_id: "go2" });
  await act(async () => root.unmount());
  host.remove();
});
it("shows two presets and compact options then starts directly without posture confirmation", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => catalog,
  } as Response);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const api = vi.fn(async () => ({}));
  await act(async () =>
    root.render(
      <SessionSetup
        state={
          {
            connection: "online",
            mode: "idle",
            robot_id: "go2",
            profile: { preset: "preview", enabled: ["camera"] },
          } as unknown as State
        }
        api={api}
        refresh={async () => {}}
        pause={async () => {}}
        onApplied={() => {}}
      />,
    ),
  );
  const button = (text: string) =>
    [...host.querySelectorAll("button")].find((b) =>
      b.textContent?.includes(text),
    )!;
  expect(host.querySelectorAll(".preset-card")).toHaveLength(2);
  expect(button("Teleop + Recording")).toBeDefined();
  expect(button("Full mode agent")).toBeDefined();
  expect(host.textContent).toContain("Includes autonomous exploration");
  await act(async () => button("Customize").click());
  const mapping = [...host.querySelectorAll("label")]
    .find((l) => l.querySelector("strong")?.textContent === "Mapping")!
    .querySelector("input")!;
  await act(async () => mapping.click());
  expect(host.textContent).toContain("Also disabled: Navigation, Exploration");
  expect(host.querySelector(".capability-option small")).toBeNull();
  expect(api).not.toHaveBeenCalled();
  await act(async () => button("Start session").click());
  expect(host.querySelector(".session-confirm")).toBeNull();
  expect(api).toHaveBeenCalledExactlyOnceWith("/session/profile", {
    preset: "map-record",
    enabled: ["lidar"],
    robot_id: "go2",
  });
  await act(async () => root.unmount());
  host.remove();
});
it("applies Vector session changes directly without a supported-surface checkbox", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const vectorCatalog = {
    ...catalog,
    robots: [
      { ...catalog.robots[0], id: "vector", kind: "vector", name: "Vector" },
    ],
  };
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => vectorCatalog,
  } as Response);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const api = vi.fn(async () => ({})),
    pause = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <SessionSetup
        state={
          {
            connection: "online",
            mode: "idle",
            robot_id: "vector",
            robot_kind: "vector",
            profile: { preset: "preview", enabled: ["camera"] },
          } as unknown as State
        }
        api={api}
        refresh={async () => {}}
        pause={pause}
        onApplied={() => {}}
      />,
    ),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent?.includes("Start session"))!
      .click(),
  );
  expect(host.querySelector(".session-confirm")).toBeNull();
  expect(api).toHaveBeenCalledExactlyOnceWith(
    "/session/profile",
    expect.objectContaining({ robot_id: "vector" }),
  );
  expect(pause).not.toHaveBeenCalled();
  await act(async () => root.unmount());
  host.remove();
});
