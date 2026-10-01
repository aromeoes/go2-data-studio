"""DimOS Vector modules with standard camera/pose streams and discoverable skills."""

import base64
import io
import json
import logging
import os
import threading
import time
from typing import Protocol

import numpy as np
from reactivex.disposable import Disposable
from dimos.agents.annotation import skill
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.stream import In, Out
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.spec.utils import Spec

from go2_setup.profiles import from_env
from go2_setup.vector.control import VectorController
from go2_setup.vector.driver import VectorDriver, EXPRESSIONS
from go2_setup.vector.tools import validate


class VectorActionSpec(Spec, Protocol):
    def vector_action(self, epoch: int, name: str, arguments: dict) -> dict: ...


class VectorConnection(Module):
    color_image: Out[Image]
    odom: Out[PoseStamped]
    vector_state: Out[str]
    tele_cmd_vel: In[Twist]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.profile = from_env()
        self.driver = VectorDriver(
            os.environ["VECTOR_IP"],
            os.environ["VECTOR_SERIAL"],
            os.environ["VECTOR_SDK_CONFIG"],
            self.profile,
        )
        self.controller = VectorController(self.driver, self.profile)
        self.done = threading.Event()
        self.count = 0
        self.last_image = None
        self.camera = None
        self.camera_received = 0

    @rpc
    def start(self):
        super().start()
        self.driver.connect()
        self.register_disposable(Disposable(self.tele_cmd_vel.subscribe(self._teleop)))
        threading.Thread(target=self._publish, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _teleop(self, msg):
        try:
            self.controller.teleop(
                self.controller.authority.epoch, msg.linear.x, msg.linear.y, msg.angular.z
            )
        except Exception as error:
            logging.getLogger(__name__).warning("Vector Teleop failed: %s", error, exc_info=True)
            self.controller.halt(reason="Teleop stopped: " + str(error))

    def _watchdog(self):
        while not self.done.wait(0.05):
            try:
                self.controller.tick()
            except Exception:
                # Repeated stop attempts if the transport recovered after a failure.
                self.controller.authority.halt()
                self.controller.reason = "Motor stop could not be confirmed"

    def _publish(self):
        while not self.done.wait(0.1):
            try:
                state = self.driver.sensor_state()
                if not state:
                    continue
                self.count += 1
                p = state["pose"]
                if p:
                    self.odom.publish(
                        PoseStamped(
                            position=[p["x"], p["y"], 0],
                            orientation=[0, 0, np.sin(p["yaw"] / 2), np.cos(p["yaw"] / 2)],
                            frame_id=f"vector_origin_{p['origin_id']}",
                            ts=state["received"],
                        )
                    )
                latest = (
                    self.driver.latest_image
                    if "camera" in self.profile["enabled"]
                    else None
                )
                if latest is not None and latest.image_id != self.last_image:
                    self.last_image = latest.image_id
                    raw = latest.raw_image.convert("RGB")
                    self.camera_received = latest.image_recv_time
                    self.color_image.publish(
                        Image.from_numpy(
                            np.asarray(raw),
                            format=ImageFormat.RGB,
                            frame_id="vector_camera",
                            ts=self.camera_received,
                        )
                    )
                    buffer = io.BytesIO()
                    raw.save(buffer, format="JPEG", quality=75)
                    self.camera = base64.b64encode(buffer.getvalue()).decode()
                state["expressions"] = [
                    k for k, v in EXPRESSIONS.items() if v in self.driver.triggers
                ]
                self.vector_state.publish(
                    json.dumps(
                        dict(
                            vector=state,
                            camera=self.camera,
                            pose=p,
                            battery={
                                "percent": None,
                                "received": state["power"]["received"] if state["power"] else None,
                            },
                            sensors={
                                "odom": {"received": state["received"], "count": self.count},
                                "color_image": {
                                    "received": self.camera_received,
                                    "count": self.last_image or 0,
                                },
                            },
                        )
                    )
                )
            except Exception as error:
                # Keep failures observable without flooding the log at sensor rate.
                now = time.monotonic()
                if now - getattr(self, "last_publish_error", 0) > 5:
                    logging.getLogger(__name__).warning("Vector telemetry publication failed: %s", error, exc_info=True)
                    self.last_publish_error = now
                # Telemetry loss becomes stale at both the local gate and supervisor.
                continue

    @rpc
    def control(self, path: str, data: dict) -> dict:
        c = self.controller
        if path == "/mode":
            return c.switch(data["mode"])
        if path == "/halt":
            return c.halt(data.get("latch", False))
        if path == "/clear":
            c.authority.clear()
            return c.state()
        if path == "/heartbeat":
            return {"ok": c.authority.renew(data["epoch"])}
        if path == "/release":
            with c.lock:
                return (
                    {**c.halt(), "ok": True}
                    if data["epoch"] == c.authority.epoch
                    else {"ok": False}
                )
        if path == "/teleop":
            return {"ok": c.teleop(data["epoch"], data["x"], data["y"], data["yaw"])}
        if path == "/agent/pause":
            with c.lock:
                if not c.authority.valid(data["epoch"], {"agent"}):
                    raise ValueError("HumanCLI control expired")
                c._stop()
                return {"ok": True}
        if path == "/vector/personality":
            return c.native()
        if path == "/hold":
            return c.set_hold(data.get("on"))
        raise ValueError("Unsupported Vector control")

    @rpc
    def set_profile(self, config: dict) -> None:
        """Session modules were added to the running connection."""
        self.profile = config
        self.driver.profile = config
        self.controller.profile = config

    @rpc
    def control_state(self) -> dict:
        return self.controller.state()

    @rpc
    def vector_action(self, epoch: int, name: str, arguments: dict) -> dict:
        arguments = validate(name, arguments)
        if name in {"visible_faces", "find_person"} and "faces" not in self.profile["enabled"]:
            raise ValueError("Native face recognition is disabled")
        if name == "visible_faces":
            with self.controller.lock:
                if not self.controller.authority.valid(epoch, {"agent"}):
                    raise ValueError("HumanCLI control expired")
                return {"faces": self.controller.check_sensors()["faces"]}
        return self.controller.start_action(epoch, name, arguments)

    @rpc
    def stop(self):
        if self.done.is_set():
            return
        self.done.set()
        try:
            self.controller.halt()
        finally:
            self.driver.close()
            super().stop()


class VectorTelemetry(Module):
    vector_state: In[str]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.latest = {}

    @rpc
    def start(self):
        super().start()
        self.register_disposable(Disposable(self.vector_state.subscribe(self._receive)))

    def _receive(self, raw):
        self.latest = json.loads(raw)

    @rpc
    def snapshot(self) -> dict:
        return self.latest


class VectorSkills(Module):
    _vector: VectorActionSpec

    @skill
    def move_relative(self, epoch: int, direction: str, distance_m: float) -> dict:
        """Request a bounded forward/backward drive under the current HumanCLI lease."""
        return self._vector.vector_action(
            epoch, "move_relative", dict(direction=direction, distance_m=distance_m)
        )

    @skill
    def set_head(self, epoch: int, angle_deg: float) -> dict:
        """Set head angle in degrees."""
        return self._vector.vector_action(epoch, "set_head", dict(angle_deg=angle_deg))

    @skill
    def set_lift(self, epoch: int, height: float) -> dict:
        """Set lift height, normalized 0 to 1."""
        return self._vector.vector_action(epoch, "set_lift", dict(height=height))

    @skill
    def speak(self, epoch: int, text: str) -> dict:
        """Speak using Vector's native voice."""
        return self._vector.vector_action(epoch, "speak", dict(text=text))

    @skill
    def play_expression(self, epoch: int, expression: str) -> dict:
        """Play a native expression, suppressing tread movement."""
        return self._vector.vector_action(epoch, "play_expression", dict(expression=expression))

    @skill
    def find_person(self, epoch: int, name: str) -> dict:
        """Search enrolled names using native face recognition and a bounded head-only scan."""
        return self._vector.vector_action(epoch, "find_person", dict(name=name))

    @skill
    def visible_faces(self, epoch: int) -> dict:
        """Read native face observations."""
        return self._vector.vector_action(epoch, "visible_faces", {})
