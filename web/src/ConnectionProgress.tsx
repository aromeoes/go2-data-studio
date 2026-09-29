import React, { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

export function ConnectionProgress({ connection, kind = "go2", replay = false }: {
  connection: string;
  kind?: string;
  replay?: boolean;
}) {
  const [elapsed, setElapsed] = useState(0);
  const waiting = connection === "connecting" || connection === "reconnecting";
  useEffect(() => {
    setElapsed(0);
    if (!waiting) return;
    const began = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - began) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [connection, waiting]);
  if (!waiting) return null;
  const robot = kind === "vector" ? "Vector" : "Go2";
  return <div className="connection-progress" aria-busy="true">
    <LoaderCircle size={18} className="connection-spinner" aria-hidden="true" />
    <div>
      <strong role="status">{replay ? "Starting replay" : connection === "reconnecting" ? `Reconnecting to ${robot}` : `Connecting to ${robot}`}</strong>
      <span className="connection-elapsed" aria-label="Time waiting">{elapsed}s</span>
      <p>{replay ? "Loading recorded data." : "Starting DimOS and waiting for fresh robot data."}
        {!replay && kind === "go2" && " Recent Deck connections took about 20–30 seconds; startup can take longer."}
        {elapsed >= 45 && " Still waiting. Check that the robot is on and reachable on this network."}
      </p>
    </div>
  </div>;
}
