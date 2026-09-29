import { useEffect, useState } from "react";

type Inputs = { axes: number[]; buttons: number[]; connected: boolean };
const neutral: Inputs = { axes: [0, 0, 0, 0], buttons: [], connected: false };
const labels = [
  "A",
  "B",
  "X",
  "Y",
  "L1",
  "R1",
  "L2",
  "R2",
  "View",
  "Menu",
  "L3",
  "R3",
  "D-pad up",
  "D-pad down",
  "D-pad left",
  "D-pad right",
  "Steam",
];
export function readController(pad?: Gamepad | null): Inputs {
  if (!pad?.connected || pad.mapping !== "standard") return neutral;
  return {
    connected: true,
    axes: Array.from({ length: 4 }, (_, i) => {
      const value = pad.axes[i];
      return Number.isFinite(value)
        ? Math.round(Math.max(-1, Math.min(1, value)) * 20) / 20
        : 0;
    }),
    buttons: labels.map((_, i) => {
      const button = pad.buttons[i];
      return button?.pressed
        ? 1
        : Number.isFinite(button?.value)
          ? Math.round(Math.max(0, Math.min(1, button.value)) * 20) / 20
          : 0;
    }),
  };
}

/** Read-only controller visualization. It never sends robot commands. */
export function ControllerDiagram() {
  const [inputs, setInputs] = useState(neutral);
  useEffect(() => {
    let frame = 0,
      last = -Infinity,
      previous = "";
    const poll = (now: number) => {
      if (now - last >= 40) {
        const pad =
          !document.hidden &&
          document.hasFocus() &&
          navigator.getGamepads &&
          Array.from(navigator.getGamepads()).find(
            (p) => p?.connected && p.mapping === "standard",
          );
        const next = readController(pad || null);
        const key = JSON.stringify(next);
        if (key !== previous) {
          setInputs(next);
          previous = key;
        }
        last = now;
      }
      frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, []);
  const down = (index: number) => (inputs.buttons[index] || 0) > 0.1;
  const names = labels.filter((_, i) => down(i));
  const left = Math.hypot(inputs.axes[0], inputs.axes[1]) > 0.18;
  const right = Math.hypot(inputs.axes[2], inputs.axes[3]) > 0.18;
  if (left) names.unshift("Left stick");
  if (right) names.push("Right stick");
  const button = (
    index: number,
    x: number,
    y: number,
    label: string,
    round = false,
    width = 32,
  ) => (
    <g
      key={index}
      className={"pad-control " + (down(index) ? "is-active" : "")}
      data-control={labels[index]}
      data-active={down(index)}
    >
      <title>
        {labels[index]}
        {index === 7 || index === 6 ? " · unassigned" : ""}
      </title>
      {round ? (
        <circle cx={x} cy={y} r={10} />
      ) : (
        <rect x={x - width / 2} y={y - 9} width={width} height={18} rx={6} />
      )}
      <text x={x} y={y + 3}>
        {label}
      </text>
    </g>
  );
  const stick = (index: number, x: number, y: number, active: boolean) => (
    <g
      className={
        "pad-control pad-stick " +
        (active || down(index === 0 ? 10 : 11) ? "is-active" : "")
      }
      data-control={index === 0 ? "Left stick" : "Right stick"}
      data-active={active || down(index === 0 ? 10 : 11)}
    >
      <title>{index === 0 ? "Left stick · move" : "Right stick · turn"}</title>
      <circle cx={x} cy={y} r={18} />
      <circle
        className="stick-thumb"
        cx={x + inputs.axes[index] * 8}
        cy={y + inputs.axes[index + 1] * 8}
        r={11}
      />
    </g>
  );
  return (
    <figure className="controller-diagram">
      <svg
        viewBox="0 0 320 150"
        role="img"
        aria-label={`Controller input: ${inputs.connected ? names.join(", ") || "neutral" : "not detected"}`}
      >
        <path
          className="pad-body"
          d="M47 30 H273 Q307 30 311 62 L314 117 Q313 139 293 137 L253 124 H67 L27 137 Q7 139 6 117 L9 62 Q13 30 47 30 Z"
        />
        <rect
          className="pad-screen"
          x="112"
          y="47"
          width="96"
          height="61"
          rx="5"
        />
        <text className="pad-center-label" x="160" y="73">
          GO2
        </text>
        <text className="pad-center-hint" x="160" y="88">
          LIVE INPUT
        </text>
        {button(6, 47, 12, "L2", false, 42)}
        {button(7, 273, 12, "R2", false, 42)}
        {button(4, 48, 34, "L1", false, 48)}
        {button(5, 272, 34, "R1", false, 48)}
        {stick(0, 48, 69, left)}
        {stick(2, 231, 102, right)}
        {button(3, 275, 57, "Y", true)}
        {button(2, 257, 75, "X", true)}
        {button(1, 293, 75, "B", true)}
        {button(0, 275, 93, "A", true)}
        {button(12, 86, 87, "↑", false, 18)}
        {button(13, 86, 119, "↓", false, 18)}
        {button(14, 70, 103, "←", false, 18)}
        {button(15, 102, 103, "→", false, 18)}
        {button(8, 94, 58, "▱", false, 18)}
        {button(9, 226, 58, "≡", false, 18)}
        {button(16, 160, 122, "STEAM", false, 44)}
      </svg>
      <figcaption>
        {inputs.connected
          ? names.length
            ? names.join(" · ")
            : "Move a stick or press a button"
          : "Press a controller button to detect it"}
      </figcaption>
    </figure>
  );
}
