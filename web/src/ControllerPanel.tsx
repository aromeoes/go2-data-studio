import { useEffect, useState } from "react";
import { ControllerDiagram } from "./ControllerDiagram";

export function ControllerPanel({ armed, vector = false }: { armed: boolean; vector?: boolean }) {
  const [name, setName] = useState("");
  useEffect(() => {
    const update = () =>
      setName(
        Array.from(navigator.getGamepads?.() || []).find((p) => p?.connected)
          ?.id || "",
      );
    update();
    const timer = setInterval(update, 500);
    return () => clearInterval(timer);
  }, []);
  const status = armed
    ? "Teleop active. Release L1 to stop. B stops."
    : "Center the sticks, then hold L1 to take Teleop control from any mode.";
  return (
    <div className="controller-panel">
      <strong>{name ? "Controller connected" : "Controller"}</strong>
      {name && <small title={name}>{name}</small>}
      <ControllerDiagram />
      <p role="status">{status}</p>
      <details className="controller-help">
        <summary>Controls and shortcuts</summary>
        <div className="controller-legend">
          <span>Left stick · {vector ? "Drive and steer" : "Move"}</span>
          <span>Right stick · Turn</span>
          <span>L1 / LB · Hold to drive</span>
          <span>B · Stop</span>
          <span>R1 · Hold to talk</span>
        </div>
        {!armed && (
          <small className="controller-navigation-hint">
            D-pad · Focus · A · Select · Right stick · Scroll. Steam + X opens
            the Deck keyboard.
          </small>
        )}
      </details>
    </div>
  );
}
