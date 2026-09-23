"""Bounded flight recorder for failures, excluding images and map payloads."""

from collections import deque
import copy
import json
from pathlib import Path
import time
import uuid


class FailureDiagnostics:
    def __init__(self, root: Path):
        self.root = root / "diagnostics"
        self.samples = deque(maxlen=90)

    def observe(self, telemetry: dict, *, elapsed: float, segment_id=None, error=None):
        now = time.time()
        row = {"time": now, "rpc_ms": round(elapsed * 1000, 2), "segment_id": segment_id}
        if error:
            row["poll_error"] = error
        # Copy only operational fields. Never persist camera frames, map cells,
        # credentials, prompts or image descriptions to a diagnostic report.
        for name in ("control", "motion", "recording", "transport"):
            row[name] = copy.deepcopy(telemetry.get(name))
        row["sensors"] = {
            name: {**sample, "age_s": now - sample["received"]}
            for name, sample in telemetry.get("sensors", {}).items()
            if sample.get("received") is not None
        }
        self.samples.append(row)

    def save(self, reason: str, *, segment_id=None) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"connection-{time.time_ns()}-{uuid.uuid4().hex[:8]}.json"
        path.write_text(
            json.dumps(
                {
                    "reason": reason,
                    "time": time.time(),
                    "segment_id": segment_id,
                    "samples": list(self.samples),
                },
                indent=2,
            )
        )
        return path
