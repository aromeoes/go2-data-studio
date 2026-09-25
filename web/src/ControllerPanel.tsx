import { useEffect, useRef, useState } from "react";
import { GamepadGate, INPUT_TIMEOUT_MS, type Motion, ZERO } from "./gamepad";

export function ControllerPanel({
  armed,
  speed,
  input,
  lost,
}: {
  armed: boolean;
  speed: number;
  input: (motion: Motion) => void;
  lost: () => void;
}) {
  const callbacks = useRef({ input, lost });
  callbacks.current = { input, lost };
  const [status, setStatus] = useState(
    "Press a controller button to detect it.",
  );
  const [name, setName] = useState("");
  useEffect(() => {
    const gate = new GamepadGate();
    let frame = 0,
      identity = "",
      last = performance.now(),
      cancelled = false;

    const lose = (message: string) => {
      gate.reset();
      callbacks.current.input(ZERO);
      if (armed && !cancelled) {
        cancelled = true;
        callbacks.current.lost();
      }
      setStatus(message);
    };
    const poll = () => {
      const now = performance.now();
      const pads = navigator.getGamepads
        ? Array.from(navigator.getGamepads())
        : [];
      const pad = identity
        ? pads.find((p) => p && `${p.index}:${p.id}` === identity)
        : pads.find((p) => p?.connected);
      if (!pad) {
        setName("");
        if (identity)
          lose(
            "Controller disconnected. Enable controls again after reconnecting.",
          );
        else setStatus("Press a controller button to detect it.");
      } else {
        if (!identity) identity = `${pad.index}:${pad.id}`;
        setName(pad.id);
        if (pad.mapping !== "standard")
          lose("Select a standard gamepad layout in Steam Input.");
        else if (armed && now - last > INPUT_TIMEOUT_MS)
          lose("Controller input paused. Enable controls again.");
        else if (armed && (document.hidden || !document.hasFocus()))
          lose("Return to the application and enable controls again.");
        else if (!cancelled) {
          const pressedStop = !!pad.buttons[1]?.pressed;
          // Global controller stop handling also covers exploration and HumanCLI.
          if (!pressedStop && armed) {
            const motion = gate.sample(pad, speed);
            if (!motion)
              lose("Controller input is unavailable. Enable controls again.");
            else {
              callbacks.current.input(motion);
              setStatus(
                "Center sticks and release LB, then hold LB to move. B stops.",
              );
            }
          } else {
            gate.reset();
            callbacks.current.input(ZERO);
            setStatus("Controller detected. Enable controls to drive.");
          }
        }
      }
      last = now;
      frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => {
      cancelAnimationFrame(frame);
      callbacks.current.input(ZERO);
    };
  }, [armed, speed]);
  return (
    <div className="controller-panel">
      <strong>{name ? "Controller connected" : "Controller"}</strong>
      {name && <small title={name}>{name}</small>}
      <p role="status">{status}</p>
      <div className="controller-legend">
        <span>Left stick · Move</span>
        <span>Right stick · Turn</span>
        <span>LB · Hold to drive</span>
        <span>B · Stop</span>
      </div>
      {!armed && <small className="controller-navigation-hint">D-pad · Focus · A · Select · Right stick · Scroll. Steam + X opens the Deck keyboard.</small>}
    </div>
  );
}
