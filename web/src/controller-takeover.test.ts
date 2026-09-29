import { describe, expect, it, vi } from "vitest";
import { ControllerTakeover } from "./controllerTakeover";
import { ZERO } from "./gamepad";
const pad = (held = false, axes = [0, 0, 0, 0], stop = false): Gamepad =>
  ({
    id: "deck",
    index: 0,
    connected: true,
    mapping: "standard",
    axes,
    buttons: Array.from({ length: 8 }, (_, i) => ({
      pressed: (i === 4 && held) || (i === 1 && stop),
    })),
  }) as unknown as Gamepad;
const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};
function fixture() {
  const release = vi.fn(),
    callbacks = {
      take: vi.fn(async (_s: AbortSignal): Promise<() => void> => release),
      input: vi.fn(),
      stop: vi.fn(),
      error: vi.fn(),
    };
  const c = new ControllerTakeover(callbacks);
  c.sample(pad(), true, 0, 0.1);
  c.sample(pad(), true, 16, 0.1);
  return { c, callbacks, release };
}
describe("L1 control takeover", () => {
  it("routes Vector steering through the same cancellable L1 lease", async () => {
    const { c, callbacks } = fixture();
    c.sample(pad(true), true, 32, 0.1, "vector");
    await flush();
    c.sample(pad(true, [-1, 0, 0, 0]), true, 48, 0.1, "vector");
    expect(callbacks.input).toHaveBeenLastCalledWith({ vx: 0, vy: 0, wz: 1.5 });
    c.sample(pad(), true, 64, 0.1, "vector");
    expect(callbacks.input).toHaveBeenLastCalledWith(ZERO);
  });
  it("takes one lease on a fresh L1 press and stops on release", async () => {
    const { c, callbacks, release } = fixture();
    c.sample(pad(true), true, 32, 0.1);
    await flush();
    c.sample(pad(true, [0, 1, 0, 0]), true, 48, 0.1);
    expect(callbacks.take).toHaveBeenCalledTimes(1);
    expect(callbacks.input.mock.lastCall?.[0].vx).toBe(-0.1);
    c.sample(pad(), true, 64, 0.1);
    expect(release).toHaveBeenCalledTimes(1);
    expect(callbacks.stop).toHaveBeenCalledTimes(1);
    expect(callbacks.input).toHaveBeenLastCalledWith(ZERO);
  });
  it("releases a late grant after L1 was released without sending movement", async () => {
    const { c, callbacks, release } = fixture();
    let grant!: (r: () => void) => void;
    callbacks.take.mockImplementation(
      () =>
        new Promise((r) => {
          grant = r;
        }),
    );
    c.sample(pad(true), true, 32, 0.1);
    const signal = callbacks.take.mock.calls[0][0];
    c.sample(pad(), true, 48, 0.1);
    expect(signal.aborted).toBe(true);
    grant(release);
    await flush();
    expect(release).toHaveBeenCalledTimes(1);
    c.sample(pad(true, [0, -1, 0, 0]), true, 64, 0.1);
    expect(
      callbacks.input.mock.calls.every(([v]) => !v.vx && !v.vy && !v.wz),
    ).toBe(true);
  });
  it("requires release and centered sticks after a held button on connection", async () => {
    const { c, callbacks } = fixture();
    c.sample(null, false, 32, 0.1);
    c.sample(pad(true), true, 48, 0.1);
    c.sample(pad(true), true, 64, 0.1);
    expect(callbacks.take).not.toHaveBeenCalled();
    c.sample(pad(), true, 80, 0.1);
    c.sample(pad(true, [0, 1, 0]), true, 96, 0.1);
    expect(callbacks.take).not.toHaveBeenCalled();
    c.sample(pad(true), true, 112, 0.1);
    expect(callbacks.take).not.toHaveBeenCalled();
    c.sample(pad(), true, 128, 0.1);
    c.sample(pad(true), true, 144, 0.1);
    await flush();
    expect(callbacks.take).toHaveBeenCalledTimes(1);
  });
  it.each(["focus", "gap", "disconnect", "B"] as const)(
    "cancels on %s and never rearms a held L1",
    async (kind) => {
      const { c, callbacks, release } = fixture();
      c.sample(pad(true), true, 32, 0.1);
      await flush();
      const now = kind === "gap" ? 400 : 48;
      c.sample(
        kind === "disconnect" ? null : pad(true, [0, 0, 0], kind === "B"),
        kind !== "focus",
        now,
        0.1,
      );
      expect(release).toHaveBeenCalledTimes(1);
      c.sample(pad(true), true, now + 16, 0.1);
      c.sample(pad(true), true, now + 32, 0.1);
      expect(callbacks.take).toHaveBeenCalledTimes(1);
    },
  );
  it("does not retry a rejected request while held", async () => {
    const { c, callbacks } = fixture();
    callbacks.take.mockRejectedValue(Error("Cliff detected"));
    c.sample(pad(true), true, 32, 0.1);
    await flush();
    c.sample(pad(true), true, 48, 0.1);
    expect(callbacks.take).toHaveBeenCalledTimes(1);
    expect(callbacks.error).toHaveBeenCalledWith("Cliff detected");
  });
});
