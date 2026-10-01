import type { ReactNode } from "react";
import { Activity } from "lucide-react";

export type VectorReadings = {
  received: number;
  cliff: { any_detected: boolean; individual: null };
  proximity: {
    distance_mm: number;
    signal_quality: number;
    found_object: boolean;
    unobstructed: boolean;
    lift_in_fov: boolean;
  } | null;
  imu: { accel: number[] | null; gyro: number[] | null; units: string };
  touch: { detected: boolean; raw: number } | null;
  power: {
    volts: number;
    level: string;
    charging: boolean;
    on_charger: boolean;
    received: number;
    percent: null;
  } | null;
  temperature: { head_c: number | null; body_c: number | null; reason: string };
  head_deg: number | null;
  lift_mm: number | null;
  wheel_mmps: number[];
  picked_up: boolean;
  falling: boolean;
  faces: { id: number; name: string | null; last_seen: number }[];
};
const number = (v: number | null | undefined, unit = "") =>
  typeof v === "number" && Number.isFinite(v)
    ? `${v.toFixed(1)}${unit}`
    : "Unavailable";
const axes = (v: number[] | null | undefined) =>
  v
    ? v.map((n, i) => `${["X", "Y", "Z"][i]} ${number(n)}`).join(" · ")
    : "Unavailable";
export function VectorSensors({
  data,
  connected,
}: {
  data?: VectorReadings;
  connected: boolean;
}) {
  const stale = !connected || !data || Date.now() / 1000 - data.received > 2;
  const p = data?.proximity;
  const powerFresh =
    data?.power && Date.now() / 1000 - data.power.received < 15;
  const rows: [string, ReactNode, string?][] = [
    [
      "Cliff",
      data
        ? data.cliff.any_detected
          ? "Detected"
          : "Not detected"
        : "Unavailable",
      "Combined detection from four sensors. Individual readings are not exposed by the SDK.",
    ],
    [
      "Distance to object",
      !p || p.lift_in_fov || !p.found_object
        ? "Unavailable"
        : number(p.distance_mm, " mm"),
      p?.lift_in_fov
        ? "Lift blocks the proximity sensor"
        : p?.unobstructed
          ? "No object detected in sensor range"
          : `Signal quality: ${number(p?.signal_quality)}`,
    ],
    [
      "Accelerometer",
      axes(data?.imu.accel),
      data?.imu.units || "SDK raw units",
    ],
    ["Gyroscope", axes(data?.imu.gyro), data?.imu.units || "SDK raw units"],
    [
      "Touch",
      data?.touch
        ? `${data.touch.detected ? "Touched" : "Not touched"} · ${data.touch.raw} raw`
        : "Unavailable",
    ],
    [
      "Power",
      data?.power
        ? `${number(data.power.volts, " V")} · ${data.power.level}${data.power.on_charger ? " · on charger" : ""}${data.power.charging ? " · charging" : ""}${powerFresh ? "" : " · stale"}`
        : "Unavailable",
      "The SDK reports voltage and charge level, not a percentage.",
    ],
    [
      "Internal temperature",
      "Unavailable",
      "Head and body temperatures are not exposed by the Vector SDK.",
    ],
    ["Head position", number(data?.head_deg, "°")],
    ["Lift position", number(data?.lift_mm, " mm")],
    [
      "Tread speed",
      data
        ? `L ${number(data.wheel_mmps[0])} · R ${number(data.wheel_mmps[1])} mm/s`
        : "Unavailable",
    ],
    [
      "Pickup / falling",
      data
        ? `${data.picked_up ? "Picked up" : "Supported"} · ${data.falling ? "Falling" : "No fall detected"}`
        : "Unavailable",
    ],
    [
      "Native faces",
      !data
        ? "Unavailable"
        : data.faces.length
          ? data.faces.map((f) => f.name || "Unknown face").join(", ")
          : "No faces currently visible",
    ],
  ];
  return (
    <section
      className={`vector-sensors panel ${stale ? "stale" : ""}`}
      aria-label="Vector sensors"
    >
      <div className="panel-head">
        <div>
          <Activity size={16} />
          <strong>Vector sensors</strong>
        </div>
        <span role="status">{stale ? "STALE / NO SIGNAL" : "LIVE"}</span>
      </div>
      <dl>
        {rows.map(([label, value, detail]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              {value}
              {detail && <small>{detail}</small>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
