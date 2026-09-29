import { useEffect, useRef, useState } from "react";
import { VoiceCapture, type VoiceCallbacks, type VoicePhase } from "./voice";
export function usePushToTalk(
  callbacks: Omit<VoiceCallbacks, "update">,
  controller: () => boolean,
) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [message, setMessage] = useState(
    "Hold R1 or the microphone button to speak.",
  );
  const latest = useRef({ callbacks, controller });
  latest.current = { callbacks, controller };
  const capture = useRef<VoiceCapture | null>(null);
  if (!capture.current)
    capture.current = new VoiceCapture({
      begin: () => latest.current.callbacks.begin(),
      valid: (epoch) => latest.current.callbacks.valid(epoch),
      release: (epoch) => latest.current.callbacks.release(epoch),
      submit: (text, epoch) => latest.current.callbacks.submit(text, epoch),
      update: (next, text) => {
        setPhase(next);
        setMessage(text);
      },
    });
  useEffect(() => {
    const voice = capture.current!;
    let frame = 0,
      previous: boolean | undefined,
      identity = "",
      last = performance.now();
    const cancel = () => voice.cancel();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel();
    };
    const hidden = () => {
      if (document.hidden) cancel();
    };
    const poll = () => {
      const now = performance.now();
      const pad =
        latest.current.controller() &&
        navigator.getGamepads &&
        Array.from(navigator.getGamepads()).find(
          (p) => p?.connected && p.mapping === "standard",
        );
      const key = pad ? `${pad.index}:${pad.id}` : "";
      const held = pad ? !!pad.buttons[5]?.pressed : false;
      const focused = !document.hidden && document.hasFocus();
      if (
        voice.run &&
        (!focused ||
          now - last > 500 ||
          (identity && identity !== key) ||
          (pad && pad.buttons[1]?.pressed) ||
          (voice.run.epoch !== undefined &&
            !latest.current.callbacks.valid(voice.run.epoch)))
      )
        cancel();
      if (pad && key === identity && focused && now - last < 500) {
        if (previous === false && held && !pad.buttons[1]?.pressed)
          void voice.start();
        if (previous === true && !held) voice.finish();
      }
      previous = focused && pad ? held : undefined;
      identity = key;
      last = now;
      frame = requestAnimationFrame(poll);
    };
    window.addEventListener("blur", cancel);
    window.addEventListener("keydown", keyboard);
    document.addEventListener("visibilitychange", hidden);
    frame = requestAnimationFrame(poll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("blur", cancel);
      window.removeEventListener("keydown", keyboard);
      document.removeEventListener("visibilitychange", hidden);
      voice.cancel();
    };
  }, []);
  return { phase, message, active: phase !== "idle", capture: capture.current };
}
