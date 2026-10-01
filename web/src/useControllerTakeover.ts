import { useEffect, useRef } from "react";
import { ControllerTakeover } from "./controllerTakeover";
import type { DriveKind, Motion } from "./gamepad";

export function useControllerTakeover(callbacks: {
  enabled: () => boolean;
  speed: () => number;
  kind: () => DriveKind;
  take: (signal: AbortSignal) => Promise<() => void>;
  input: (value: Motion) => void;
  stop: () => void;
  error: (message: string) => void;
}) {
  const current = useRef(callbacks);
  current.current = callbacks;
  useEffect(() => {
    const control = new ControllerTakeover({
      take: (signal) => current.current.take(signal),
      input: (value) => current.current.input(value),
      stop: () => current.current.stop(),
      error: (message) => current.current.error(message),
    });
    let frame = 0;
    const poll = () => {
      const pad =
        Array.from(navigator.getGamepads?.() || []).find((p) => p?.connected) ||
        null;
      control.sample(
        pad,
        current.current.enabled() && !document.hidden && document.hasFocus(),
        performance.now(),
        current.current.speed(),
        current.current.kind(),
      );
      frame = requestAnimationFrame(poll);
    };
    const cancel = () => control.cancel();
    window.addEventListener("blur", cancel);
    document.addEventListener("visibilitychange", cancel);
    frame = requestAnimationFrame(poll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("blur", cancel);
      document.removeEventListener("visibilitychange", cancel);
      control.cancel();
    };
  }, []);
}
