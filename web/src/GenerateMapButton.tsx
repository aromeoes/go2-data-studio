import React from "react";
export function GenerateMapButton({ recording, pending, mode, onGenerate }: {
  recording: boolean; pending: boolean; mode: string; onGenerate: () => void;
}) {
  const reason = recording ? "Save this recording before generating its map." : pending ? "Wait for the current action to finish." : "";
  return <div className="generate-map-action">
    <button disabled={!!reason} title={reason || "Generate a map locally from this recording"} onClick={onGenerate}>
      {mode !== "idle" ? "Pause & generate map" : "Generate map"}
    </button>
    {reason && <small>{reason}</small>}
  </div>;
}
