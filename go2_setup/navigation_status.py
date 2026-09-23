"""Read-only explanations of the pinned planner's logs and observed motion."""

from collections import deque
import math
from pathlib import Path
import re
import time


class NavigationStatus:
    def __init__(self, log_path, clock=time.time):
        self.path = Path(log_path) if log_path else None
        self.clock = clock
        self.offset = self.path.stat().st_size if self.path and self.path.exists() else 0
        self.identity = None
        self.pending = b""
        self.events = deque(maxlen=8)
        self.phase = "waiting"
        self.warning = None
        self.epoch = None
        self.anchor = None
        self.direction = None

    def _event(self, code, text, warning=False):
        now = self.clock()
        if self.events and self.events[-1]["code"] == code:
            self.events[-1].update(ts=now, count=self.events[-1]["count"] + 1)
        else:
            self.events.append(dict(code=code, text=text, ts=now, count=1, source="planner"))
        if warning:
            self.warning = dict(code=code, text=text, ts=now, source="planner")

    def feed(self, line):
        # stdout is shared by every module. Match only known planner messages.
        if not any(
            name in line
            for name in ("local_planner.py", "global_planner.py", "frontier_goal_selector.py")
        ):
            return
        if "Obstacle detected ahead" in line:
            self._event(
                "obstacle", "The planner detected an obstacle and stopped the maneuver.", True
            )
        elif "Robot is stuck. Replanning." in line:
            self._event("stuck", "The planner detected no progress and is replanning.", True)
        elif "No path found to the goal" in line or "No safe goal found" in line:
            self.phase = "no_path"
            self._event("no_path", "No safe route to the goal was found.", True)
        elif "Replanning." in line or "Replanning path due to obstacle" in line:
            self.phase = "replanning"
            self._event("replanning", "Recalculating the route.")
        elif "Found path " in line:
            self.phase = "route_ready"
            if self.warning and self.warning["code"] == "no_path":
                self.warning = None
            self._event("route_ready", "A route to the goal was found.")
        elif "changed state" in line:
            match = re.search(
                r"state=(initial_rotation|path_following|final_rotation|arrived|idle)\b", line
            )
            if match:
                phase = match.group(1)
                # An idle transition during replan does not explain why it stopped.
                if phase != "idle":
                    self.phase = phase
                    self._event(phase, PHASES[phase][0])
        elif "Published frontier goal:" in line:
            self.phase = "planning"
            self._event("planning", "Exploration selected a new goal.")
        elif "Goal timeout" in line:
            self._event("timeout", "The goal timed out; exploration is choosing another.", True)
        elif "Arrived at goal." in line or "Accepting as arrived." in line:
            self.phase = "arrived"
            self.warning = None
            self._event("arrived", PHASES["arrived"][0])

    def read(self):
        if self.path is None:
            return
        try:
            stat = self.path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if (
                self.identity is not None and self.identity != identity
            ) or stat.st_size < self.offset:
                self.offset, self.pending = 0, b""
            self.identity = identity
            with self.path.open("rb") as stream:
                # Bound work per poll even if unrelated logs are very noisy.
                if stat.st_size - self.offset > 65536:
                    self.offset = stat.st_size - 65536
                    self.pending = b""
                    stream.seek(self.offset)
                    stream.readline()
                else:
                    stream.seek(self.offset)
                data = self.pending + stream.read(65536)
                self.offset = stream.tell()
            parts = data.split(b"\n")
            self.pending = parts.pop()
            for line in parts:
                self.feed(line.decode("utf-8", errors="replace"))
        except OSError:
            pass

    def snapshot(self, telemetry):
        now = self.clock()
        control = telemetry.get("control", {})
        mode = control.get("mode", "idle")
        if control.get("epoch") != self.epoch:
            self.epoch = control.get("epoch")
            self.anchor = self.direction = self.warning = None
            self.phase = "waiting"
        self.read()
        warnings = []
        active = mode in {"explore", "agent"}
        if active and self.warning and now - self.warning["ts"] < 10:
            warnings.append(dict(self.warning))
        pose = telemetry.get("pose")
        odom = telemetry.get("sensors", {}).get("odom", {}).get("received", 0)
        command = telemetry.get("motion", {}).get("last") or {}
        direction = (
            "translation"
            if math.hypot(command.get("x", 0), command.get("y", 0)) > 0.02
            else "rotation"
            if abs(command.get("yaw", 0)) > 0.05
            else None
        )
        if (
            active
            and pose
            and direction
            and 0 <= now - odom < 1
            and 0 <= now - command.get("received", 0) < 1
        ):
            if self.anchor is None or direction != self.direction:
                self.anchor = (now, dict(pose))
                self.direction = direction
            started, before = self.anchor
            distance = math.hypot(pose["x"] - before["x"], pose["y"] - before["y"])
            angle = abs(
                math.atan2(
                    math.sin(pose["yaw"] - before["yaw"]), math.cos(pose["yaw"] - before["yaw"])
                )
            )
            progress = distance > 0.02 if direction == "translation" else angle > 0.035
            if progress:
                self.anchor = (now, dict(pose))
            elif now - started >= 4:
                text = (
                    "Rotation commands are being sent, but no rotation has been observed for at least 4 s."
                    if direction == "rotation"
                    else "Movement commands are being sent, but no displacement has been observed for at least 4 s."
                )
                warnings.append(
                    dict(code="no_observed_motion", text=text, ts=now, source="odometry")
                )
        else:
            self.anchor = self.direction = None
        if control.get("stop_reason"):
            warnings.append(
                dict(code="control_stopped", text=control["stop_reason"], ts=now, source="control")
            )
        phase = self.phase if active else "teleop" if mode == "teleop" else "paused"
        title, detail = PHASES.get(phase, PHASES["waiting"])
        return dict(
            phase=phase,
            title=title,
            detail=detail,
            warnings=warnings,
            events=[dict(event) for event in reversed(self.events)],
        )


PHASES = {
    "waiting": ("Waiting for a goal", "No navigation maneuver has been confirmed yet."),
    "planning": ("Finding a route", "Exploration selected an area to visit."),
    "route_ready": ("Route found", "The planner found a route to the goal."),
    "initial_rotation": (
        "Turning to follow the route",
        "The robot is aligning first; forward motion has not been requested yet.",
    ),
    "path_following": (
        "Following the route",
        "The planner is sending movement commands.",
    ),
    "final_rotation": (
        "Adjusting final orientation",
        "The robot reached the position and is aligning.",
    ),
    "replanning": ("Recalculating route", "Looking for an updated route."),
    "no_path": ("No safe route", "No route to the goal was found in the current map."),
    "arrived": ("Goal reached", "The planner reported the route is complete."),
    "teleop": ("Manual control", "Movement is controlled by the keyboard or buttons."),
    "paused": ("Navigation paused", "No autonomous mission is active."),
}
