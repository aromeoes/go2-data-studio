import math
import threading
import time


# Maximum age of an already received Go2 position, LiDAR or map update.
GO2_SENSOR_TIMEOUT_SECONDS = 10.0


def go2_sensor_recent(received: float, now: float) -> bool:
    return received > 0 and now - received <= GO2_SENSOR_TIMEOUT_SECONDS


class Authority:
    """A renewable control lease. Old tokens never become valid again."""

    def __init__(self, clock=time.monotonic, wall_clock=time.time) -> None:
        self.clock = clock
        self.wall_clock = wall_clock
        self.lock = threading.RLock()
        self.epoch = 0
        self.mode = "idle"
        self.deadline = 0.0
        self.wall_deadline = 0.0
        self.estop = False

    def transition(self, mode: str) -> int:
        if mode not in {"idle", "teleop", "explore", "agent"}:
            raise ValueError("Unknown mode")
        with self.lock:
            if self.estop and mode != "idle":
                raise ValueError("Release stop first")
            self.epoch += 1
            self.mode = mode
            self.deadline = self.clock() + (0.6 if mode == "teleop" else 2.0)
            self.wall_deadline = self.wall_clock() + (0.6 if mode == "teleop" else 2.0)
            return self.epoch

    def valid(self, epoch: int, modes: set[str]) -> bool:
        with self.lock:
            return (
                not self.estop
                and epoch == self.epoch
                and self.mode in modes
                and self.clock() < self.deadline
                and self.wall_clock() < self.wall_deadline
            )

    def renew(self, epoch: int) -> bool:
        with self.lock:
            if not self.valid(epoch, {"teleop", "explore", "agent"}):
                return False
            self.deadline = self.clock() + (0.6 if self.mode == "teleop" else 2.0)
            self.wall_deadline = self.wall_clock() + (0.6 if self.mode == "teleop" else 2.0)
            return True

    def halt(self, latch: bool = False) -> int:
        with self.lock:
            self.epoch += 1
            self.mode = "idle"
            self.deadline = 0.0
            self.wall_deadline = 0.0
            self.estop = self.estop or latch
            return self.epoch

    def clear(self) -> None:
        with self.lock:
            self.estop = False


def bounded_velocity(x: float, y: float, yaw: float) -> tuple[float, float, float]:
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        raise ValueError("Invalid velocity")
    # Forward speed comes from the selected Teleop speed or DimOS planner.
    # Do not silently reduce the upstream Go2 defaults (0.5 / 0.55 m/s).
    return x, max(-0.2, min(0.2, y)), max(-0.5, min(0.5, yaw))
