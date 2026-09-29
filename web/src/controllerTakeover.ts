import {
  GamepadGate,
  INPUT_TIMEOUT_MS,
  ZERO,
  axis,
  type Motion,
  type DriveKind,
} from "./gamepad";

type Callbacks = {
  take: (signal: AbortSignal) => Promise<() => void>;
  input: (value: Motion) => void;
  stop: () => void;
  error: (message: string) => void;
};

/** A new, neutral L1 press owns one cancellable control lease. */
export class ControllerTakeover {
  private gate = new GamepadGate();
  private identity = "";
  private previous: boolean | undefined;
  private last = -Infinity;
  private attempt: AbortController | null = null;
  private release: (() => void) | null = null;
  private pending = false;
  constructor(private callbacks: Callbacks) {}
  cancel() {
    const active = !!this.attempt;
    this.attempt?.abort();
    this.attempt = null;
    if (active) {
      this.callbacks.input(ZERO);
      this.callbacks.stop();
    }
    this.release?.();
    this.release = null;
    this.gate.reset();
    this.previous = undefined;
  }
  sample(pad: Gamepad | null, enabled: boolean, now: number, speed: number, kind: DriveKind = "go2") {
    const identity = pad ? `${pad.index}:${pad.id}` : "";
    const stale = now - this.last > INPUT_TIMEOUT_MS;
    this.last = now;
    if (
      !enabled ||
      !pad ||
      !pad.connected ||
      pad.mapping !== "standard" ||
      identity !== this.identity ||
      stale
    ) {
      this.cancel();
      this.identity = identity;
      return;
    }
    const value = this.gate.sample(pad, speed, kind);
    if (!value || pad.buttons[1]?.pressed || pad.buttons[5]?.pressed) {
      this.cancel(); // B stop and R1 voice always preempt driving.
      return;
    }
    const held = !!pad.buttons[4]?.pressed;
    if (!held) {
      if (this.attempt) this.cancel();
      // Seed neutral observation after cancellation for the next deliberate press.
      this.gate.sample(pad, speed, kind);
      this.previous = false;
      return;
    }
    const edge = this.previous === false;
    this.previous = true;
    if (edge && !this.attempt && !this.pending) {
      if (pad.axes.slice(0, 3).some((v) => axis(v) !== 0)) {
        this.callbacks.error(
          "Center the sticks, release L1, then hold L1 to drive.",
        );
        return;
      }
      const attempt = new AbortController();
      this.attempt = attempt;
      this.pending = true;
      void this.callbacks
        .take(attempt.signal)
        .then((release) => {
          if (attempt.signal.aborted || this.attempt !== attempt) release();
          else this.release = release;
        })
        .catch((error) => {
          if (!attempt.signal.aborted) {
            this.cancel();
            this.previous = true; // Failure never retries until release and a new press.
            this.callbacks.error(
              error instanceof Error ? error.message : String(error),
            );
          }
        })
        .finally(() => {
          this.pending = false;
        });
    }
    if (this.release && this.attempt) this.callbacks.input(value);
  }
}
