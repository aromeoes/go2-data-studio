import { describe, expect, it, vi } from "vitest";
import { TeleopMachine } from "@dimos/sdk/internal/teleop";
import { AnalogInput, GamepadGate, ZERO, axis } from "./gamepad";

function pad(axes = [0, 0, 0, 0], held = false): Gamepad {
  return {
    connected: true,
    mapping: "standard",
    axes,
    buttons: Array.from({ length: 5 }, (_, n) => ({
      pressed: held && n === 4,
      touched: false,
      value: 0,
    })),
  } as unknown as Gamepad;
}
describe("controller authority and analog input", () => {
  it("steers Vector with the left stick, keeping right-stick turning as an alias", () => {
    const gate = new GamepadGate();
    gate.sample(pad(), 0.1, "vector");
    expect(gate.sample(pad([-1, -1, 1], true), 0.1, "vector"))
      .toEqual({ vx: 0.1, vy: 0, wz: 1.5 });
    expect(gate.sample(pad([1, 0, 0], true), 0.1, "vector")?.wz).toBe(-1.5);
    expect(gate.sample(pad([0, 0, -1], true), 0.1, "vector")?.wz).toBe(1.5);
    expect(gate.sample(pad([0, -0.59, 0], true), 0.1, "vector")?.vx).toBeCloseTo(0.05);
    expect(gate.sample(pad([0.1, -0.1, 0.1], true), 0.1, "vector")).toEqual(ZERO);
    expect(gate.sample(pad([-1, -1, 0], false), 0.1, "vector")).toEqual(ZERO);
  });
  it("requires centered sticks and a released bumper before movement", () => {
    const gate = new GamepadGate();
    expect(gate.sample(pad([0, -1, 0], true), 0.5)).toEqual(ZERO);
    gate.sample(pad(), 0.5);
    expect(gate.sample(pad([0, -1, 0], true), 0.5)?.vx).toBe(0.5);
    gate.sample(pad([0, -1, 0], false), 0.5);
    expect(gate.sample(pad([0, -1, 0], true), 0.5)).toEqual(ZERO);
  });
  it("rejects unknown layouts, invalid axes and disconnected controllers", () => {
    const gate = new GamepadGate();
    expect(gate.sample({ ...pad(), mapping: "" }, 0.5)).toBeNull();
    expect(gate.sample({ ...pad(), connected: false }, 0.5)).toBeNull();
    expect(gate.sample(pad([NaN, 0, 0]), 0.5)).toBeNull();
    expect(gate.sample(pad(), Infinity)).toBeNull();
  });
  it("keeps the deadzone and lateral/yaw limits independent of forward speed", () => {
    expect(axis(0.1)).toBe(0);
    const gate = new GamepadGate();
    gate.sample(pad(), 1);
    const result = gate.sample(pad([-1, -1, -1], true), 1)!;
    expect(result.vx).toBeLessThan(1);
    expect(result.vy).toBeLessThanOrEqual(0.2);
    expect(result.wz).toBe(0.5);
  });
  it("preserves SDK zero and stop messages and expires stale analog input", () => {
    let time = 0;
    const input = new AnalogInput(() => time);
    input.selected = true;
    input.update({ vx: 0.2, vy: 0.1, wz: -0.3 });
    const twist = { t: "twist", vx: 0.5, vy: 0, wz: 0, seq: 12, ts: 3 };
    expect(input.map(twist)).toEqual({ ...twist, vx: 0.2, vy: 0.1, wz: -0.3 });
    expect(input.map({ ...twist, vx: 0 })).toEqual({ ...twist, vx: 0 });
    expect(input.map({ t: "stop", seq: 13 })).toEqual({ t: "stop", seq: 13 });
    time = 201;
    expect(input.map(twist)).toEqual({ ...twist, ...ZERO });
  });
  it("uses the real SDK lease and stops on release and disarm", () => {
    vi.useFakeTimers();
    try {
      const input = new AnalogInput(() => 0);
      input.selected = true;
      const wire = vi.fn();
      const machine = new TeleopMachine(
        { maxLinear: 0.5, maxAngular: 0.5, boost: 1, publishHz: 15 },
        {
          control: vi.fn(),
          datagram: (message) => wire(input.map(message)),
        },
      );
      input.update({ vx: 0.1, vy: 0.05, wz: 0.2 });
      machine.arm();
      machine.keyDown("KeyW");
      expect(wire).not.toHaveBeenCalled();
      machine.onRelayMsg({ t: "teleop_started" } as any);
      machine.keyDown("KeyW");
      expect(wire.mock.lastCall?.[0]).toMatchObject({
        vx: 0.1,
        vy: 0.05,
        wz: 0.2,
      });
      machine.keyUp("KeyW");
      expect(wire.mock.lastCall?.[0]).toMatchObject(ZERO);
      vi.advanceTimersByTime(250);
      const count = wire.mock.calls.length;
      vi.advanceTimersByTime(2000);
      expect(wire).toHaveBeenCalledTimes(count);
      machine.disarm("test finished");
      expect(wire.mock.lastCall?.[0]).toMatchObject(ZERO);
    } finally {
      vi.useRealTimers();
    }
  });
});
