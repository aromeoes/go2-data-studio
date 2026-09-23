import { BatteryMedium } from "lucide-react";
import type { NavigationInfo, State } from "./types";

export function BatteryStatus({
  state,
  connected,
}: {
  state: State;
  connected: boolean;
}) {
  const battery = state.telemetry.battery;
  const percent = battery?.percent;
  const valid = typeof percent === "number" && percent >= 0 && percent <= 100;
  const age = battery?.received
    ? Date.now() / 1000 - battery.received
    : Infinity;
  const fresh = connected && age >= 0 && age < 10;
  const text = !valid
    ? "Battery unavailable"
    : `${percent}%${state.replay ? " · replay" : !fresh ? " · stale" : ""}`;
  return (
    <span
      className={`battery-status ${valid && fresh && percent <= 20 ? "low" : ""}`}
      title={fresh ? "Charge reported by Go2" : "No recent battery reading"}
      aria-label={`Battery: ${text}`}
    >
      <BatteryMedium size={16} aria-hidden="true" />
      {text}
    </span>
  );
}

const sourceLabel = (source: string) =>
  ({
    planner: "Planner",
    odometry: "Observed motion",
    control: "Control",
  })[source] || source;

export function NavigationPanel({
  navigation,
}: {
  navigation?: NavigationInfo;
}) {
  if (!navigation)
    return (
      <div className="navigation-status">
        <p>Waiting for navigation status</p>
      </div>
    );
  return (
    <div className="navigation-status">
      <div role="status" aria-live="polite">
        <strong>{navigation.title}</strong>
        <p>{navigation.detail}</p>
        {navigation.warnings.map((warning) => (
          <div className="navigation-warning" key={warning.code}>
            <small>{sourceLabel(warning.source)}</small>
            <p>{warning.text}</p>
          </div>
        ))}
      </div>
      {navigation.events.length > 0 && (
        <details>
          <summary>Recent messages</summary>
          <ol>
            {navigation.events.map((event, index) => (
              <li key={`${event.code}-${index}`}>
                <time dateTime={new Date(event.ts * 1000).toISOString()}>
                  {new Date(event.ts * 1000).toLocaleTimeString("en-US", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </time>
                <span>
                  {event.text}
                  {event.count > 1 ? ` (${event.count} times)` : ""}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
