"""Saved-map identity and coordinate conversion, independent of the robot runtime."""

import hashlib
import math
from pathlib import Path

import numpy as np


def selected_map(catalog, map_id):
    if not map_id:
        return None
    item = catalog.get(map_id, "map")
    if item.get("status") != "ready":
        raise ValueError("Select a completed map")
    segment = catalog.get(item["parent"], "segment")
    session = catalog.get(segment["parent"], "session")
    space = catalog.get(session["parent"], "space")
    path = Path(item["map_path"]).resolve()
    if not path.is_relative_to(catalog.root.resolve()) or not path.is_file():
        raise ValueError("Saved map is missing or outside the library")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "id": item["id"],
        "space_id": space["id"],
        "space_name": space["name"],
        "segment_id": segment["id"],
        "path": str(path),
        "fingerprint": digest,
    }


def transform_pose(matrix, pose):
    matrix = np.asarray(matrix, dtype=float)
    point = matrix @ [pose["x"], pose["y"], pose.get("z", 0), 1]
    direction = matrix[:3, :3] @ [math.cos(pose["yaw"]), math.sin(pose["yaw"]), 0]
    return dict(
        x=float(point[0]),
        y=float(point[1]),
        z=float(point[2]),
        yaw=math.atan2(direction[1], direction[0]),
    )


class MatchAcceptance:
    """Reject weak matches and require successive consistent registration results."""

    def __init__(self, fitness=0.90, rmse=0.08, confirmations=3):
        self.fitness, self.rmse, self.confirmations = fitness, rmse, confirmations
        self.previous = None
        self.count = 0

    def evaluate(self, matrix, fitness, rmse):
        matrix = np.asarray(matrix, dtype=float)
        self.reason = None

        def reject(code, message):
            self.previous, self.count = None, 0
            self.reason = code
            return False, message

        if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
                or not math.isfinite(fitness) or not math.isfinite(rmse) or rmse < 0):
            return reject("invalid_result", "Matcher returned an invalid alignment; retrying.")
        rotation = matrix[:3, :3]
        if (not np.allclose(rotation.T @ rotation, np.eye(3), atol=0.001)
                or abs(np.linalg.det(rotation) - 1) >= 0.001
                or not np.allclose(matrix[3], [0, 0, 0, 1])):
            return reject("invalid_transform", "Matcher returned a non-rigid alignment; retrying.")
        tilt = math.degrees(math.acos(float(np.clip(rotation[2, 2], -1, 1))))
        if tilt > 10:
            return reject(
                "tilted_alignment",
                f"Rejected tilted alignment ({tilt:.1f}°, limit 10°). Searching for another match.",
            )
        if fitness < self.fitness:
            return reject(
                "low_overlap",
                f"Map overlap {fitness:.1%}; need at least {self.fitness:.0%}. "
                "Collect more shared room geometry with Teleop.",
            )
        if rmse > self.rmse:
            return reject(
                "high_error",
                f"Fit error {rmse * 100:.1f} cm; limit {self.rmse * 100:.0f} cm. "
                "Searching for a closer alignment.",
            )
        consistent = True
        if self.previous is not None:
            delta = matrix @ np.linalg.inv(self.previous)
            angle = math.acos(float(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1)))
            consistent = np.linalg.norm(delta[:3, 3]) <= 0.25 and angle <= math.radians(5)
            self.count = self.count + 1 if consistent else 1
        else:
            self.count = 1
        self.previous = matrix.copy()
        accepted = self.count >= self.confirmations
        self.reason = "accepted" if accepted else "confirming" if consistent else "inconsistent_alignment"
        return accepted, (
            "Alignment verified"
            if accepted
            else f"Verifying alignment ({self.count}/{self.confirmations})"
            if consistent
            else f"Candidate location changed by more than 25 cm or 5°. Restarting verification (1/{self.confirmations})."
        )
