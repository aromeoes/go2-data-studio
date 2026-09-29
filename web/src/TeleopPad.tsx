import { useState, type PointerEvent } from "react";
import { ControllerPanel } from "./ControllerPanel";
import { robot } from "./sdk";

export function TeleopPad({
  vector = false,
  armed,
  speed,
  setSpeed,
  disabled,
  pressed,
  toggle,
  press,
  release,
}: {
  vector?: boolean;
  armed: boolean;
  speed: number;
  setSpeed: (speed: number) => void;
  disabled: boolean;
  pressed: string[];
  toggle: () => void;
  press: (key: string) => void;
  release: (key: string) => void;
}) {
  const [source, setSource] = useState<"keyboard" | "controller">(
    robot.inputSource || "keyboard",
  );
  const rows = [
    [
      ["q", "←", "Move left"],
      ["w", "↑", "Move forward"],
      ["e", "→", "Move right"],
    ],
    [
      ["a", "↶", "Turn left"],
      ["s", "↓", "Move backward"],
      ["d", "↷", "Turn right"],
    ],
  ];
  const end = (event: PointerEvent<HTMLButtonElement>, key: string) => {
    release(key);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return (
    <div className="teleop">
      <label className="teleop-speed">
        Input
        <select
          aria-label="Control input"
          value={source}
          disabled={armed}
          onChange={(event) => {
            const next = event.target.value as "keyboard" | "controller";
            robot.selectInput(next);
            setSource(next);
          }}
        >
          <option value="keyboard">Keyboard / touch</option>
          <option value="controller">Controller</option>
        </select>
      </label>
      <p role="status">
        {armed
          ? source === "controller"
            ? "Teleop active. Release L1 to stop."
            : "Controls enabled. Hold a key or button to move."
          : source === "controller"
            ? "Hold L1 to take Teleop control."
            : "Select an input and enable controls to move."}
      </p>
      <label className="teleop-speed">
        Forward speed
        <select
          aria-label="Teleop forward speed"
          value={speed}
          disabled={armed}
          onChange={(event) => setSpeed(Number(event.target.value))}
        >
          {vector ? (
            <>
              <option value={0.05}>0.05 m/s · Slow</option>
              <option value={0.1}>0.10 m/s · Default</option>
              <option value={0.12}>0.12 m/s · Fast</option>
            </>
          ) : (
            <>
              <option value={0.25}>0.25 m/s · Slow</option>
              <option value={0.5}>0.5 m/s · Default</option>
              <option value={1}>1.0 m/s · Boost</option>
            </>
          )}
        </select>
      </label>
      {source === "controller" ? (
        <ControllerPanel armed={armed} vector={vector} />
      ) : (
        rows.map((row, index) => (
          <div className="key-row" key={index}>
            {row
              .filter(([key]) => !vector || !["q", "e"].includes(key))
              .map(([key, arrow, label]) => (
                <button
                  key={key}
                  className={`drive-key ${pressed.includes(key) ? "pressed" : ""}`}
                  disabled={disabled || !armed}
                  aria-label={`${key.toUpperCase()}: ${label}`}
                  aria-pressed={pressed.includes(key)}
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    press(key);
                  }}
                  onPointerUp={(event) => end(event, key)}
                  onPointerCancel={(event) => end(event, key)}
                  onLostPointerCapture={() => release(key)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      press(key);
                    }
                  }}
                  onKeyUp={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      release(key);
                    }
                  }}
                  onBlur={() => release(key)}
                >
                  <span>
                    {key.toUpperCase()} {arrow}
                  </span>
                </button>
              ))}
          </div>
        ))
      )}
      <small>Release to stop · Space or Esc to halt</small>
      {source !== "controller" && (
        <button
          className={armed ? "armed" : "primary"}
          disabled={disabled}
          onClick={toggle}
        >
          {armed ? "Disable controls" : "Enable controls"}
        </button>
      )}
    </div>
  );
}
