/** Standard Gamepad input. No robot transport or automatic arming lives here. */
export type Motion = { vx: number; vy: number; wz: number };
export const ZERO: Motion = { vx: 0, vy: 0, wz: 0 };
export const INPUT_TIMEOUT_MS = 200;

export function axis(value: number, deadzone = 0.18) {
  if (!Number.isFinite(value)) throw Error("Invalid controller axis");
  const magnitude = Math.min(1, Math.abs(value));
  return magnitude <= deadzone
    ? 0
    : Math.sign(value) * ((magnitude - deadzone) / (1 - deadzone)) ** 1.5;
}

export class GamepadGate {
  private neutralSeen = false;
  reset() {
    this.neutralSeen = false;
  }
  sample(pad: Gamepad, speed: number): Motion | null {
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
      forward = -axis(pad.axes[1]);
      lateral = -axis(pad.axes[0]);
      turn = -axis(pad.axes[2]);
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
