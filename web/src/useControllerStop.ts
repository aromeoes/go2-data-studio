import { useEffect, useRef } from "react";

/** B is a software stop in every control mode while controller input is selected. */
export function useControllerStop(enabled: () => boolean, stop: () => void) {
  const callbacks = useRef({ enabled, stop });
  callbacks.current = { enabled, stop };
  useEffect(() => {
    let frame = 0;
    const previous = new Map<string, boolean>();
    const poll = () => {
      const visible = !document.hidden && document.hasFocus();
      const pads = navigator.getGamepads
        ? Array.from(navigator.getGamepads())
        : [];
      const present = new Set<string>();
      for (const pad of pads) {
        if (!pad?.connected || pad.mapping !== "standard") continue;
        const key = `${pad.index}:${pad.id}`;
        present.add(key);
        const held = !!pad.buttons[1]?.pressed;
        if (
          visible &&
          callbacks.current.enabled() &&
          held &&
          previous.get(key) === false
        ) {
          callbacks.current.stop();
        }
        previous.set(key, held);
      }
      for (const key of previous.keys())
        if (!present.has(key)) previous.delete(key);
      frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, []);
}
