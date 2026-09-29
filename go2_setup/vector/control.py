"""One control owner, bounded actions and a robot-local motor watchdog.

SDK default priority retains Vector's mandatory reactions. No override priority,
Go2 commands, free-form SDK method invocation or autonomous roaming is accepted.
"""

import math
import threading
import time
from concurrent.futures import Future

from go2_setup.control import Authority


def resolve(value, timeout=2):
    return value.result(timeout=timeout) if isinstance(value, Future) else value


class ForwardBlocked(ValueError):
    """Forward proximity blocks a command, not every direction of Teleop."""


class VectorController:
    MAX_SPEED_MMPS = 120.0
    MAX_YAW_RPS = 1.5
    TRACK_MM = 70.0  # Nominal differential-drive geometry; bounded wheel commands below.

    def __init__(self, driver, profile, clock=time.monotonic):
        self.driver, self.profile, self.clock = driver, profile, clock
        self.authority = Authority(clock=clock)
        self.lock = self.authority.lock
        self.owned = False
        self.last_drive = 0.0
        self.driving = False
        self.future = None
        self.action = None
        self.reason = None
        self.operation = 0
        self.preempted = False
        self.stop_pending = False
        self.forward_blocked = False

    def state(self):
        with self.lock:
            return dict(
                mode=self.authority.mode,
                epoch=self.authority.epoch,
                estop=self.authority.estop,
                stop_reason=self.reason,
                motor_stop_pending=self.stop_pending,
                ownership="stopped"
                if self.authority.estop
                else ("app" if self.owned else "native"),
                action=self.action,
            )

    def check_sensors(self, forward=False):
        s = self.driver.sensor_state()
        if not s or time.time() - s["received"] > 1:
            raise ValueError("Vector sensor stream is stale")
        if s["cliff"]["any_detected"] or s["picked_up"] or s["falling"]:
            raise ValueError("Vector reports a cliff, pickup or fall")
        p = s.get("proximity")
        if forward and (not p or p["lift_in_fov"] or not (p["found_object"] or p["unobstructed"])):
            raise ForwardBlocked("Vector has no clear forward proximity reading. Back up or turn to reposition.")
        if forward and p["found_object"] and p["distance_mm"] < 100:
            raise ForwardBlocked("Object within 100 mm: forward movement blocked. Back up or turn to reposition.")
        return s

    def switch(self, mode):
        if mode not in {"idle", "teleop", "agent"}:
            raise ValueError("Vector does not support mapping or autonomous exploration")
        with self.lock:
            capability = {"teleop": "teleop", "agent": "humancli"}.get(mode)
            if capability and capability not in self.profile["enabled"]:
                raise ValueError("This control mode is disabled")
            if mode != "idle":
                if self.authority.estop:
                    raise ValueError("Release stop first")
                self.check_sensors()
                if mode == "teleop":
                    self.driver.acquire()
                    self.owned = True
            self._stop()
            if mode == "agent" and self.owned:
                self.driver.release()
                self.owned = False
            self.reason = None
            self.forward_blocked = False
            epoch = self.authority.transition(mode)
            return dict(epoch=epoch, mode=mode)

    def _stop(self):
        self.operation += 1
        if self.future is not None:
            self.future.cancel()
            self.future = None
        self.driving = False
        if self.action and self.action.get("status") == "running":
            self.action = {**self.action, "status": "cancelled"}
        if self.owned:
            # A delayed/rejected drive acknowledgement must NEVER suppress stop.
            # has_control() also includes motion_error, so it is not a stop gate.
            self.stop_pending = True
            self.driver.stop_motors()
            self.stop_pending = False

    def halt(self, latch=False, reason=None):
        with self.lock:
            if latch and not self.owned:
                self.driver.acquire()
                self.owned = True
            self.authority.halt(latch)
            self.forward_blocked = False
            self.reason = reason
            self._stop()
            return self.state()

    def native(self):
        with self.lock:
            if self.authority.estop:
                raise ValueError("Release stop before resuming native personality")
            if self.authority.mode != "idle":
                raise ValueError("Pause app controls first")
            self._stop()
            if self.owned:
                self.driver.release()
            self.owned = False
            return self.state()

    def teleop(self, epoch, x, y, yaw):
        with self.lock:
            if not self.authority.valid(epoch, {"teleop"}):
                return False
            if not all(math.isfinite(v) for v in (x, y, yaw)):
                raise ValueError("Invalid velocity")
            if abs(y) > 0.001:
                self._stop()
                raise ValueError("Vector cannot drive sideways")
            try:
                self.check_sensors(forward=x > 0)
            except ForwardBlocked as error:
                # Keep the same control lease so a deliberate reverse/turn can
                # move away. Never issue any part of the blocked forward twist.
                # Avoid flooding the SDK with identical stops at gamepad rate.
                if not self.forward_blocked or self.driving or self.stop_pending:
                    self._stop()
                self.forward_blocked = True
                self.reason = str(error)
                return False
            except ValueError as error:
                self.halt(reason=str(error))
                return False
            if x == 0 and yaw == 0:
                # Release is a stop command, not another acceleration-limited drive.
                self._stop()
                return True
            speed = max(-self.MAX_SPEED_MMPS, min(self.MAX_SPEED_MMPS, x * 1000))
            turn = max(-self.MAX_YAW_RPS, min(self.MAX_YAW_RPS, yaw)) * self.TRACK_MM / 2
            self._wheels(speed - turn, speed + turn)
            if self.forward_blocked:
                self.forward_blocked = False
                self.reason = None
            self.last_drive = self.clock()
            return True

    def _wheels(self, left, right):
        scale = max(1.0, abs(left) / self.MAX_SPEED_MMPS, abs(right) / self.MAX_SPEED_MMPS)
        self.driver.wheels(left / scale, right / scale)
        self.driving = bool(left or right)

    def tick(self):
        with self.lock:
            if self.stop_pending:
                self._stop()
            if self.authority.mode != "idle":
                try:
                    if not self.authority.valid(self.authority.epoch, {"agent", "teleop"}):
                        raise ValueError("App control lease expired")
                    self.check_sensors()
                    if self.owned and not self.driver.has_control():
                        fault = getattr(self.driver, "motion_error", None)
                        if isinstance(fault, str) and fault:
                            self.halt(reason=fault)
                            return
                        if not self.preempted:
                            self._stop()
                        self.preempted = True
                        self.reason = "Vector native reaction has priority; app motion paused"
                        return
                    self.preempted = False
                    if (
                        self.authority.mode == "teleop"
                        and self.driving
                        and self.clock() - self.last_drive > 0.25
                    ):
                        self._stop()
                except ValueError as error:
                    self.halt(reason=str(error))

    def start_action(self, epoch, name, args):
        with self.lock:
            if not self.authority.valid(epoch, {"agent"}):
                raise ValueError("HumanCLI control expired")
            if self.action and self.action.get("status") == "running":
                raise ValueError("Wait for the current Vector action or stop it")
            self.check_sensors()
            if not self.owned:
                self.driver.acquire()
                self.owned = True
            if not self.driver.has_control():
                raise ValueError(
                    "Vector is handling a native reaction. Try again when it finishes."
                )
            if not self.authority.valid(epoch, {"agent"}):
                self.halt(reason="HumanCLI lease expired while acquiring Vector")
                raise ValueError("HumanCLI control expired")
            self.check_sensors()
            self.operation += 1
            operation = self.operation
            self.action = dict(name=name, status="running", started=time.time())
            thread = threading.Thread(
                target=self._run, args=(operation, epoch, name, args), daemon=True
            )
            thread.start()
            return dict(accepted=True, completed=False, action=name)

    def _valid(self, operation, epoch):
        return operation == self.operation and self.authority.valid(epoch, {"agent"})

    def _run(self, operation, epoch, name, args):
        try:
            if name == "move_relative":
                result = self._move(operation, epoch, args)
            elif name == "find_person":
                result = self._find(operation, epoch, args["name"])
            else:
                with self.lock:
                    if not self._valid(operation, epoch):
                        return
                    self.future = self.driver.action(name, args)
                    future = self.future
                deadline = self.clock() + 20
                while not future.done():
                    with self.lock:
                        if not self._valid(operation, epoch):
                            future.cancel()
                            return
                        self.check_sensors()
                    if self.clock() > deadline:
                        raise ValueError("Vector action timed out; outcome unconfirmed")
                    time.sleep(0.05)
                response = future.result()
                # SDK responses can carry a failed action without raising.
                self.driver.validate_result(response)
                result = {"completed": True}
            with self.lock:
                if self._valid(operation, epoch):
                    self.action = {**self.action, "status": "completed", "result": result}
                    self.future = None
                    # Native trigger-word listening is below SDK default priority.
                    # Yield between completed agent actions so onboard speech works.
                    self.driver.release()
                    self.owned = False
        except Exception as error:
            with self.lock:
                if operation == self.operation:
                    self.halt(reason="Vector action stopped: " + str(error))
                    self.action = dict(name=name, status="failed", error=str(error))

    def _move(self, operation, epoch, args):
        distance = args["distance_m"]
        sign = 1 if args["direction"] == "forward" else -1
        start = self.check_sensors(forward=sign > 0)["pose"]
        if not start:
            raise ValueError("Vector position is unavailable")
        deadline = self.clock() + distance / 0.08 + 3
        while self.clock() < deadline:
            with self.lock:
                if not self._valid(operation, epoch):
                    return {"completed": False}
                s = self.check_sensors(forward=sign > 0)
                pose = s["pose"]
                if not pose or pose["origin_id"] != start["origin_id"]:
                    raise ValueError("Vector localization origin changed")
                delta = pose["yaw"] - start["yaw"]
                if abs(math.atan2(math.sin(delta), math.cos(delta))) > math.radians(20):
                    raise ValueError("Vector heading changed during the drive")
                progress = sign * (
                    (pose["x"] - start["x"]) * math.cos(start["yaw"])
                    + (pose["y"] - start["y"]) * math.sin(start["yaw"])
                )
                if progress >= distance:
                    self.driver.stop_motors()
                    self.driving = False
                    return {"completed": True, "distance_m": progress}
                self._wheels(sign * 80, sign * 80)
            time.sleep(0.05)
        raise ValueError("Movement timed out before reaching the requested distance")

    def _find(self, operation, epoch, name):
        if "faces" not in self.profile["enabled"]:
            raise ValueError("Native face recognition is disabled")
        # Head-only search. No roaming, photo identity inference or Go2 navigation.
        for angle in (0, 20, 40):
            with self.lock:
                if not self._valid(operation, epoch):
                    return {"found": False, "cancelled": True}
                self.future = self.driver.action("set_head", {"angle_deg": angle})
            deadline = self.clock() + 2
            while self.clock() < deadline:
                with self.lock:
                    if not self._valid(operation, epoch):
                        return {"found": False, "cancelled": True}
                    s = self.check_sensors()
                    matches = [
                        f
                        for f in s["faces"]
                        if f.get("name", "")
                        and f["name"].casefold() == name.casefold()
                        and time.time() - f["last_seen"] < 2
                    ]
                    if matches:
                        return {
                            "found": True,
                            "faces": matches,
                            "source": "Vector onboard recognition",
                        }
                time.sleep(0.1)
        return {
            "found": False,
            "message": "Not seen during a head-only scan. This is not a search of the room.",
        }
