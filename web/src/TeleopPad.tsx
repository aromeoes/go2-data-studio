import type { PointerEvent } from "react";

export function TeleopPad({
  armed,
  speed,
  setSpeed,
  disabled,
  pressed,
  toggle,
  press,
  release,
}: {
  armed: boolean;
  speed: number;
  setSpeed: (speed: number) => void;
  disabled: boolean;
  pressed: string[];
  toggle: () => void;
  press: (key: string) => void;
  release: (key: string) => void;
}) {
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
      <p role="status">
        {armed
          ? "Controls enabled. Hold a key or button to move."
          : "Enable controls to use the keyboard or buttons."}
      </p>
      <label className="teleop-speed">
        Forward speed
        <select
          aria-label="Teleop forward speed"
          value={speed}
          disabled={armed}
          onChange={(event) => setSpeed(Number(event.target.value))}
        >
          <option value={0.25}>0.25 m/s · Slow</option>
          <option value={0.5}>0.5 m/s · Default</option>
          <option value={1}>1.0 m/s · Boost</option>
        </select>
      </label>
      {rows.map((row, index) => (
        <div className="key-row" key={index}>
          {row.map(([key, arrow, label]) => (
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
      ))}
      <small>Release to stop · Space or Esc to halt</small>
      <button
        className={armed ? "armed" : "primary"}
        disabled={disabled}
        onClick={toggle}
      >
        {armed ? "Disable controls" : "Enable controls"}
      </button>
    </div>
  );
}
