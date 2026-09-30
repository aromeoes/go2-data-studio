export type RobotSkillState = {
  active: string | null;
  phase: string;
  message: string;
  places: { name: string; usable: boolean }[];
};

export function RobotSkillStatus({ state }: { state?: RobotSkillState | null }) {
  if (!state) return null;
  return (
    <section className="robot-skill-status" aria-label="Robot skill status">
      <div role="status" aria-live="polite">
        <strong>{state.active?.replaceAll("_", " ") || "Robot skills"}</strong>
        <span className={state.phase === "error" ? "error" : ""}>{state.message}</span>
      </div>
      {state.places.length > 0 && (
        <details>
          <summary>Named places ({state.places.length})</summary>
          <ul>
            {state.places.map((place) => (
              <li key={place.name}>
                {place.name}: {place.usable ? "ready" : "requires matching map or a new tag"}
              </li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary>Try a patrol demo</summary>
        <ol>
          <li>Use Full mode agent. Teleop around the open area until it appears on the live map.</li>
          <li>Switch to HumanCLI and say “Start patrolling this area.” Keep the control page active.</li>
          <li>Say “Stop patrol” to pause, or take over with Teleop. Use Emergency stop when needed.</li>
        </ol>
        <p>Patrol uses the current navigation map, including the saved map after relocalization. Custom routes are not supported yet.</p>
      </details>
    </section>
  );
}
