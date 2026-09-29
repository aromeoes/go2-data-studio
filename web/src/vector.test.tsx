// @vitest-environment happy-dom
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import { VectorSensors, type VectorReadings } from "./VectorSensors";
import { TeleopPad } from "./TeleopPad";
import { robot } from "./sdk";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

function render(element: React.ReactNode) {
  const node = document.createElement("div");
  document.body.append(node);
  const root = createRoot(node);
  act(() => root.render(element));
  return {
    node,
    close() {
      act(() => root.unmount());
      node.remove();
    },
  };
}
const data: VectorReadings = {
  received: Date.now() / 1000,
  cliff: { any_detected: true, individual: null },
  proximity: {
    distance_mm: 87,
    signal_quality: 0.9,
    found_object: true,
    unobstructed: false,
    lift_in_fov: false,
  },
  imu: { accel: [1, 2, 3], gyro: [4, 5, 6], units: "SDK raw" },
  touch: { detected: true, raw: 900 },
  power: {
    volts: 4.1,
    level: "nominal",
    charging: false,
    on_charger: false,
    received: Date.now() / 1000,
    percent: null,
  },
  temperature: { head_c: null, body_c: null, reason: "Not exposed" },
  head_deg: 20,
  lift_mm: 32,
  wheel_mmps: [0, 0],
  picked_up: false,
  falling: false,
  faces: [{ id: 1, name: "Tule", last_seen: Date.now() / 1000 }],
};

describe("Vector UI", () => {
  it("shows measurements, native names and explicit unavailable temperatures without an invented battery percentage", () => {
    const r = render(<VectorSensors data={data} connected />);
    expect(r.node.textContent).toContain("87.0 mm");
    expect(r.node.textContent).toContain("4.1 V");
    expect(r.node.textContent).toContain("Tule");
    expect(r.node.textContent).toContain("20.0°");
    expect(r.node.textContent).toContain("32.0 mm");
    expect(r.node.textContent).toContain("Internal temperatureUnavailable");
    expect(r.node.textContent).not.toContain("100%");
    r.close();
  });
  it("marks stale readings and does not present occluded proximity as a valid distance", () => {
    const r = render(
      <VectorSensors
        data={{
          ...data,
          received: 1,
          proximity: { ...data.proximity!, lift_in_fov: true },
        }}
        connected
      />,
    );
    expect(r.node.textContent).toContain("STALE");
    expect(r.node.textContent).toContain("Lift blocks");
    expect(r.node.textContent).not.toContain("87.0 mm");
    r.close();
  });
  it("offers bounded Vector speeds and no strafe buttons, preserving six Go2 keys", () => {
    const props = {
      armed: false,
      speed: 0.1,
      setSpeed: vi.fn(),
      disabled: false,
      pressed: [],
      toggle: vi.fn(),
      press: vi.fn(),
      release: vi.fn(),
    };
    const vector = render(<TeleopPad {...props} vector />);
    expect(vector.node.querySelectorAll(".drive-key")).toHaveLength(4);
    expect(vector.node.querySelector('option[value="0.12"]')).toBeTruthy();
    expect(vector.node.querySelector('option[value="1"]')).toBeFalsy();
    vector.close();
    const go2 = render(<TeleopPad {...props} speed={0.5} />);
    expect(go2.node.querySelectorAll(".drive-key")).toHaveLength(6);
    go2.close();
  });
  it("uses L1 instead of an Enable controls button for controller input", () => {
    robot.selectInput("controller");
    const r = render(
      <TeleopPad
        vector
        armed={false}
        speed={0.1}
        setSpeed={vi.fn()}
        disabled={false}
        pressed={[]}
        toggle={vi.fn()}
        press={vi.fn()}
        release={vi.fn()}
      />,
    );
    expect(r.node.textContent).toContain("Hold L1");
    expect(r.node.textContent).not.toContain("Enable controls");
    r.close();
    robot.selectInput("keyboard");
  });
  it("ignores physical Q/E keys for Vector but keeps Go2 strafe", () => {
    const machine = { keyDown: vi.fn(), keyUp: vi.fn() };
    (robot as any).machine = machine;
    robot.embodiment = "vector";
    robot.keys(new Set(["q", "w"]));
    expect(machine.keyDown).toHaveBeenCalledWith("KeyW");
    expect(machine.keyDown).not.toHaveBeenCalledWith("KeyQ");
    robot.embodiment = "go2";
    robot.keys(new Set(["q"]));
    expect(machine.keyDown).toHaveBeenCalledWith("KeyQ");
    (robot as any).machine = null;
  });
});
