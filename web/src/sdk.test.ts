import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TeleopMachine } from "@dimos/sdk/internal/teleop";
import { RobotSDK } from "./sdk";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function controls() {
  const control = vi.fn(),
    datagram = vi.fn();
  const machine = new TeleopMachine(
    { maxLinear: 0.5, maxAngular: 0.5, boost: 1, publishHz: 15 },
    { control, datagram },
  );
  const robot = new RobotSDK();
  robot.machine = machine;
  robot.ready = true;
  return { robot, machine, control, datagram };
}

describe("custom UI uses the SDK Teleop machine", () => {
  it("does not send movement before the relay grants the exclusive lease", () => {
    const { robot, machine, datagram, control } = controls();
    robot.arm(0.5);
    robot.keys(new Set(["w"]));
    expect(control).toHaveBeenCalledWith({ t: "teleop_start" });
    expect(datagram).not.toHaveBeenCalled();
    machine.onRelayMsg({ t: "teleop_started" } as any);
    robot.keys(new Set(["w"]));
    expect(datagram.mock.lastCall![0]).toMatchObject({
      t: "twist",
      vx: 0.5,
      vy: 0,
      wz: 0,
    });
    robot.disarm();
  });
  it("Q/E strafe and A/D rotate with the existing key design", () => {
    const { robot, machine, datagram } = controls();
    robot.arm(0.5);
    machine.onRelayMsg({ t: "teleop_started" } as any);
    robot.keys(new Set(["q"]));
    expect(datagram.mock.lastCall![0]).toMatchObject({ vx: 0, vy: 0.5, wz: 0 });
    robot.keys(new Set(["e"]));
    expect(datagram.mock.lastCall![0]).toMatchObject({
      vx: 0,
      vy: -0.5,
      wz: 0,
    });
    robot.keys(new Set(["a"]));
    expect(datagram.mock.lastCall![0]).toMatchObject({ vx: 0, vy: 0, wz: 0.5 });
    robot.disarm();
  });
  it("sends zero on release then goes silent so it cannot cancel exploration", () => {
    const { robot, machine, datagram } = controls();
    robot.arm(0.5);
    machine.onRelayMsg({ t: "teleop_started" } as any);
    robot.keys(new Set(["w"]));
    vi.advanceTimersByTime(200);
    robot.keys(new Set());
    vi.advanceTimersByTime(250);
    expect(datagram.mock.lastCall![0]).toMatchObject({ vx: 0, vy: 0, wz: 0 });
    const count = datagram.mock.calls.length;
    vi.advanceTimersByTime(2000);
    expect(datagram).toHaveBeenCalledTimes(count);
    robot.disarm();
  });
  it("drops held keys on connection loss and never resumes them on reconnect", () => {
    const { robot, machine, datagram } = controls();
    robot.arm(1);
    machine.onRelayMsg({ t: "teleop_started" } as any);
    robot.keys(new Set(["w"]));
    machine.connectionChanged(false);
    const count = datagram.mock.calls.length;
    vi.advanceTimersByTime(5000);
    machine.connectionChanged(true);
    expect(datagram).toHaveBeenCalledTimes(count);
    expect(machine.getSnapshot().phase).toBe("disarmed");
  });
  it("a refused lease cannot move or release another viewer", () => {
    const { robot, machine, datagram, control } = controls();
    robot.arm(0.5);
    machine.onRelayMsg({ t: "error", code: "teleop_held" } as any);
    robot.keys(new Set(["w"]));
    robot.disarm();
    expect(datagram).not.toHaveBeenCalled();
    expect(control).toHaveBeenCalledTimes(1);
  });
});
