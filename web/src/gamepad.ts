/** Standard Gamepad input. No robot transport or automatic arming lives here. */
export type Motion = { vx: number; vy: number; wz: number };
export type DriveKind = "go2" | "vector";
export const ZERO: Motion = { vx: 0, vy: 0, wz: 0 };
export const INPUT_TIMEOUT_MS = 200;

export function axis(value: number, deadzone = 0.18, exponent = 1.5) {
  if (!Number.isFinite(value)) throw Error("Invalid controller axis");
  const magnitude = Math.min(1, Math.abs(value));
  return magnitude <= deadzone
    ? 0
    : Math.sign(value) * ((magnitude - deadzone) / (1 - deadzone)) ** exponent;
}

export class GamepadGate {
  private neutralSeen = false;
  reset() {
    this.neutralSeen = false;
  }
  sample(pad: Gamepad, speed: number, kind: DriveKind = "go2"): Motion | null {
    if (
      !pad.connected ||
      pad.mapping !== "standard" ||
      pad.axes.length < 3 ||
      pad.buttons.length < 5
    )
      return null;
    if (!Number.isFinite(speed) || speed <= 0 || speed > 1) return null;
    let forward, lateral, turn;
    try {
      const exponent = kind === "vector" ? 1 : 1.5;
      forward = -axis(pad.axes[1], 0.18, exponent);
      lateral = -axis(pad.axes[0], 0.18, exponent);
      turn = -axis(pad.axes[2], 0.18, exponent);
    } catch {
      return null;
    }
    const bumper = pad.buttons[4].pressed;
    const neutral = forward === 0 && lateral === 0 && turn === 0;
    if (!bumper) {
      this.neutralSeen = neutral;
      return ZERO;
    }
    if (!this.neutralSeen) return ZERO;
    if (kind === "vector") {
      // Differential drive: left stick steers, right stick is a turn alias.
      // Never add the sticks together or normalize forward speed as strafing.
      const steering = lateral !== 0 ? lateral : turn;
      return { vx: forward * speed || 0, vy: 0, wz: steering * 1.5 || 0 };
    }
    const length = Math.max(1, Math.hypot(forward, lateral));
    return {
      vx: (forward / length) * speed,
      vy: (lateral / length) * Math.min(speed, 0.2),
      wz: turn * 0.5,
    };
  }
}

/** Supplies analog values at the SDK's cadence without replacing its lease,
 * sequence numbers, stop messages or zero-on-release behavior. */
export class AnalogInput {
  value: Motion = ZERO;
  received = -Infinity;
  selected = false;
  constructor(private clock = () => performance.now()) {}
  update(value: Motion) {
    this.value = value;
    this.received = this.clock();
  }
  reset() {
    this.value = ZERO;
    this.received = -Infinity;
  }
  stale() {
    return this.clock() - this.received > INPUT_TIMEOUT_MS;
  }
  map<T extends { t: string; vx?: number; vy?: number; wz?: number }>(
    message: T,
  ): T {
    if (!this.selected || message.t !== "twist") return message;
    // SDK-generated zeros always stay zero, including disarm and release bursts.
    if (!message.vx && !message.vy && !message.wz) return message;
    return { ...message, ...(this.stale() ? ZERO : this.value) };
  }
}
