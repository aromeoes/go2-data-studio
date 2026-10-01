"""External DimOS modules. The upstream checkout stays unchanged."""

import base64
import copy
import queue
import threading
import time
from pathlib import Path

import numpy as np
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.stream import In, Out
from dimos.memory.store.sqlite import SqliteStore
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.nav_msgs.Path import Path as NavPath
from dimos.msgs.sensor_msgs.CameraInfo import CameraInfo
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.msgs.tf2_msgs.TFMessage import TFMessage
from dimos.robot.unitree.go2.connection import GO2Connection
from dimos.navigation.frontier_exploration.wavefront_frontier_goal_selector import (
    WavefrontFrontierExplorer,
)

from go2_setup.control import Authority, bounded_velocity, go2_sensor_recent
from go2_setup.profiles import from_env, enabled, require
from go2_setup.lidar_startup import enable_lidar, subscribe_lidar_status
from go2_setup.motion_transport import install_velocity_transport


class ConsoleExplorer(WavefrontFrontierExplorer):
    """End the frontier producer before handing control to another mode.

    The console's gate and planner cancellation own stopping. Publishing a new
    goal at the current pose while cancelling the planner races its goal callback.
    """

    @rpc
    def stop_exploration(self) -> bool:
        was_active = self.exploration_active
        self.exploration_active = False
        self.no_gain_counter = 0
        self.stop_event.set()
        thread = self.exploration_thread
        if thread and thread is not threading.current_thread():
            deadline = time.monotonic() + 5
            while thread.is_alive() and time.monotonic() < deadline:
                # Also wake a wait started just after an in-flight goal calculation.
                self.goal_reached_event.set()
                thread.join(timeout=0.05)
            if thread.is_alive():
                raise RuntimeError("Exploration is still stopping. Wait before changing modes.")
        return was_active


class PassiveGo2Connection(GO2Connection):
    """Connect sensors without the upstream automatic standup/liedown side effects."""

    @rpc
    def start(self) -> None:
        Module.start(self)
        session_profile = from_env()
        self._camera_done = threading.Event()
        self._battery = {"percent": None, "received": None}
        self._sensor_health = {}
        self._lidar_enable = {"requested": None, "error": None}
        self._lidar_status = {"received": None, "data": None}
        adapted = install_velocity_transport(self.connection)
        self._motion = {
            "count": 0,
            "sent": 0,
            "errors": 0,
            "last": None,
            "error": None,
            "transport": (
                "velocity (MCF msg)"
                if adapted
                else "velocity"
                if self.config.velocity_api
                else "joystick"
            ),
        }
        self.connection.start()
        if enabled(session_profile, "lidar"):
            self._subscribe_sensor("lidar", self.connection.lidar_stream(), self.lidar.publish)
        self._subscribe_sensor("odom", self.connection.odom_stream(), self._publish_tf)
        self._subscribe_sensor("lowstate", self.connection.lowstate_stream(), self._on_lowstate)
        self.register_disposable(Disposable(self.cmd_vel.subscribe(self._receive_velocity)))
        if enabled(session_profile, "camera"):
            self._subscribe_sensor(
                "color_image", self.connection.video_stream(), self.color_image.publish
            )

        status_subscription = subscribe_lidar_status(self.connection, self._on_lidar_status)
        if status_subscription is not None:
            self.register_disposable(status_subscription)
        try:
            # Keep the established sensor startup for onboard localization.
            # The profile controls app consumption, never LiDAR power.
            if enable_lidar(self.connection):
                self._lidar_enable["requested"] = time.time()
        except Exception as error:
            self._lidar_enable["error"] = str(error)

        def camera_info_loop():
            while not self._camera_done.wait(1):
                if enabled(session_profile, "camera"):
                    self.camera_info.publish(self.camera_info_static.with_ts(time.time()))

        threading.Thread(target=camera_info_loop, daemon=True).start()

    def _on_lidar_status(self, msg):
        self._lidar_status = {"received": time.time(), "data": str(msg.get("data"))[:2000]}

    def _subscribe_sensor(self, name, stream, callback):
        state = {"count": 0, "received": None, "published": None, "error": None}
        self._sensor_health[name] = state

        def receive(msg):
            state["count"] += 1
            state["received"] = time.time()
            try:
                callback(msg)
                state["published"] = time.time()
            except Exception as error:
                state["error"] = str(error)
                raise

        def failed(error):
            state["error"] = str(error)

        self.register_disposable(stream.subscribe(receive, on_error=failed))

    @rpc
    def transport_state(self):
        connection = self.connection
        peer = getattr(getattr(connection, "conn", None), "pc", None)
        datachannel = getattr(getattr(connection, "conn", None), "datachannel", None)
        channel = getattr(getattr(datachannel, "pub_sub", None), "channel", None)
        return {
            "sensors": {name: dict(state) for name, state in self._sensor_health.items()},
            "peer": getattr(peer, "connectionState", None),
            "ice": getattr(peer, "iceConnectionState", None),
            "channel": getattr(channel, "readyState", None),
            "buffered_bytes": getattr(channel, "bufferedAmount", None),
            "lidar_enable": dict(self._lidar_enable),
            "lidar_status": dict(self._lidar_status),
        }

    def _receive_velocity(self, msg):
        self._motion["count"] += 1
        self._motion["last"] = {
            "x": msg.linear.x,
            "y": msg.linear.y,
            "yaw": msg.angular.z,
            "received": time.time(),
        }
        try:
            if not self.move(msg):
                raise RuntimeError("Go2 transport rejected the velocity command")
            self._motion["sent"] += 1
            self._motion["error"] = None
        except Exception as error:
            self._motion["errors"] += 1
            self._motion["error"] = str(error)

    @rpc
    def motion_state(self):
        # A sent message is not an acknowledgement of physical motion.
        return dict(self._motion)

    def _on_lowstate(self, msg):
        super()._on_lowstate(msg)
        try:
            percent = msg["data"]["bms_state"]["soc"]
            if isinstance(percent, bool) or not isinstance(percent, (int, float)):
                return
            if not 0 <= percent <= 100:
                return
            self._battery = {"percent": int(percent), "received": time.time()}
        except (KeyError, TypeError):
            pass

    @rpc
    def battery_state(self):
        return dict(self._battery)

    @rpc
    def stop(self) -> None:
        self._camera_done.set()
        try:
            self.connection.stop_movement()
            self.connection.stop()
        finally:
            Module.stop(self)


class ControlGate(Module):
    hold = False  # Movement toggle; see set_hold.
    global_costmap: In[OccupancyGrid]
    lidar: In[PointCloud2]
    nav_cmd_vel: In[Twist]
    tele_cmd_vel: In[Twist]
    odom: In[PoseStamped]
    cmd_vel: Out[Twist]
    teleop_requested: Out[Twist]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.profile = from_env()
        self.authority = Authority()
        self.last_odom = 0.0
        self.last_lidar = 0.0
        self.last_map = 0.0
        self.last_teleop = 0.0
        self.done = threading.Event()
        self.navigation_enabled = False
        # Movement toggle: while held, no teleop or navigation velocity reaches the robot.
        self.hold = False
        self.nav_received = 0
        self.nav_forwarded = 0
        self.last_nav = None
        self.stop_reason = None

    @rpc
    def start(self):
        super().start()
        self.register_disposable(Disposable(self.odom.subscribe(self._odom)))
        self.register_disposable(Disposable(self.lidar.subscribe(self._lidar)))
        self.register_disposable(Disposable(self.global_costmap.subscribe(self._map)))
        self.register_disposable(Disposable(self.nav_cmd_vel.subscribe(self._nav)))
        self.register_disposable(Disposable(self.tele_cmd_vel.subscribe(self._sdk_teleop)))
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _sdk_teleop(self, msg):
        # The relay owns exclusive browser leases and its generation watchdog.
        # The product gate still enforces mode, fresh odometry and stop latch.
        self.teleop(self.authority.epoch, msg.linear.x, msg.linear.y, msg.angular.z)

    def _map(self, msg):
        self.last_map = time.monotonic()

    def _lidar(self, msg):
        self.last_lidar = time.monotonic()

    def _odom(self, msg):
        self.last_odom = time.monotonic()

    def _nav(self, msg):
        with self.authority.lock:
            self.nav_received += 1
            self.last_nav = {
                "x": msg.linear.x,
                "y": msg.linear.y,
                "yaw": msg.angular.z,
                "received": time.time(),
            }
            if (
                self.navigation_enabled
                and not self.hold
                and enabled(self.profile, "navigation")
                and self.authority.valid(self.authority.epoch, {"explore", "agent"})
                and go2_sensor_recent(self.last_odom, time.monotonic())
                and go2_sensor_recent(self.last_lidar, time.monotonic())
                and go2_sensor_recent(self.last_map, time.monotonic())
            ):
                x, y, yaw = bounded_velocity(msg.linear.x, msg.linear.y, msg.angular.z)
                self.cmd_vel.publish(Twist((x, y, 0), (0, 0, yaw)))
                self.nav_forwarded += 1

    def _watchdog(self):
        while not self.done.wait(0.05):
            with self.authority.lock:
                if self.authority.mode != "idle" and (
                    not self.authority.valid(self.authority.epoch, {"teleop", "explore", "agent"})
                    or not go2_sensor_recent(self.last_odom, time.monotonic())
                    or (
                        (
                            self.authority.mode == "explore"
                            or (self.authority.mode == "agent" and self.navigation_enabled)
                        )
                        and (
                            not go2_sensor_recent(self.last_lidar, time.monotonic())
                            or not go2_sensor_recent(self.last_map, time.monotonic())
                        )
                    )
                ):
                    self.stop_reason = (
                        "Page control lease expired"
                        if not self.authority.valid(
                            self.authority.epoch, {"teleop", "explore", "agent"}
                        )
                        else "Control stopped because position, LiDAR, or map data is missing or over 10 seconds old"
                    )
                    self.authority.halt()
                    self.cmd_vel.publish(Twist())
                elif self.authority.mode == "teleop" and time.monotonic() - self.last_teleop > 0.25:
                    self.cmd_vel.publish(Twist())

    @rpc
    def navigation(self, epoch: int, enabled: bool) -> bool:
        with self.authority.lock:
            if not self.authority.valid(epoch, {"agent"}):
                return False
            if enabled:
                require(self.profile, "navigation")
                if (
                    not go2_sensor_recent(self.last_lidar, time.monotonic())
                    or not go2_sensor_recent(self.last_map, time.monotonic())
                    or not go2_sensor_recent(self.last_odom, time.monotonic())
                ):
                    raise ValueError("Wait for recent position, LiDAR and map data")
            self.navigation_enabled = enabled
            self.cmd_vel.publish(Twist())
            return True

    @rpc
    def skill_velocity(self, epoch: int, x: float, y: float, yaw: float) -> bool:
        with self.authority.lock:
            if not self.authority.valid(epoch, {"agent"}) or not self.navigation_enabled:
                return False
            before = self.nav_forwarded
            self._nav(Twist((x, y, 0), (0, 0, yaw)))
            return self.nav_forwarded > before

    @rpc
    def switch(self, mode: str) -> int:
        with self.authority.lock:
            capability = {"teleop": "teleop", "explore": "exploration", "agent": "humancli"}.get(
                mode
            )
            if capability:
                require(self.profile, capability)
            self.navigation_enabled = mode == "explore"
            self.cmd_vel.publish(Twist())
            self.stop_reason = None
            return self.authority.transition(mode)

    @rpc
    def halt(self, latch: bool = False) -> int:
        with self.authority.lock:
            token = self.authority.halt(latch)
            self.cmd_vel.publish(Twist())
            return token

    @rpc
    def set_profile(self, config: dict) -> None:
        """Session modules were added to the running connection."""
        with self.authority.lock:
            self.profile = config

    @rpc
    def set_hold(self, on: bool) -> None:
        with self.authority.lock:
            self.hold = bool(on)
            if self.hold:
                self.cmd_vel.publish(Twist())

    @rpc
    def clear(self) -> None:
        self.authority.clear()

    @rpc
    def heartbeat(self, epoch: int) -> bool:
        return self.authority.renew(epoch)

    @rpc
    def teleop(self, epoch: int, x: float, y: float, yaw: float) -> bool:
        with self.authority.lock:
            bounded = bounded_velocity(x, y, yaw)
            self.teleop_requested.publish(Twist((x, y, 0), (0, 0, yaw)))
            if (
                not enabled(self.profile, "teleop")
                or self.hold
                or not self.authority.valid(epoch, {"teleop"})
                or not go2_sensor_recent(self.last_odom, time.monotonic())
            ):
                return False
            x, y, yaw = bounded
            self.last_teleop = time.monotonic()
            self.cmd_vel.publish(Twist((x, y, 0), (0, 0, yaw)))
            return True

    @rpc
    def state(self) -> dict:
        return dict(
            mode=self.authority.mode,
            epoch=self.authority.epoch,
            estop=self.authority.estop,
            navigation_enabled=self.navigation_enabled,
            nav_received=self.nav_received,
            nav_forwarded=self.nav_forwarded,
            last_nav=self.last_nav,
            stop_reason=self.stop_reason,
            hold=self.hold,
        )

    @rpc
    def stop(self):
        self.halt()
        self.done.set()
        super().stop()


class ConsoleBridge(Module):
    dedicated_worker = True
    teleop_requested: In[Twist]
    cmd_vel: In[Twist]
    lidar: In[PointCloud2]
    color_image: In[Image]
    camera_info: In[CameraInfo]
    odom: In[PoseStamped]
    tf: In[TFMessage]
    global_costmap: In[OccupancyGrid]
    path: In[NavPath]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lock = threading.RLock()
        self.telemetry = {"sensors": {}, "map": None, "pose": None, "path": [], "camera": None}
        self.latest_pose = None
        self.writer = None
        self.last_preview = 0.0

    @rpc
    def start(self):
        super().start()
        for name in ("lidar", "color_image", "camera_info", "odom", "tf", "teleop_requested", "cmd_vel"):
            self.register_disposable(
                Disposable(
                    getattr(self, name).subscribe(lambda msg, name=name: self._sensor(name, msg))
                )
            )
        self.register_disposable(Disposable(self.global_costmap.subscribe(self._map)))
        self.register_disposable(Disposable(self.path.subscribe(self._path)))

    def _sensor(self, name, msg):
        with self.lock:
            current = self.telemetry["sensors"].setdefault(name, {"count": 0})
            current.update(
                count=current["count"] + 1, received=time.time(), ts=getattr(msg, "ts", None)
            )
            if name == "odom":
                self.latest_pose = copy.deepcopy(msg)
                q = msg.orientation
                yaw = float(
                    np.arctan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
                )
                self.telemetry["pose"] = {
                    "x": msg.position.x,
                    "y": msg.position.y,
                    "z": msg.position.z,
                    "yaw": yaw,
                }
            if self.writer:
                record_msg = msg
                if name == "camera_info" and self.latest_pose is not None:
                    record_msg = msg.with_ts(self.latest_pose.ts)
                self.writer.enqueue(
                    name,
                    record_msg,
                    self.latest_pose
                    if name in {"lidar", "odom", "color_image", "teleop_requested", "cmd_vel"}
                    else None,
                )
            if name == "color_image" and time.monotonic() - self.last_preview > 0.4:
                self.last_preview = time.monotonic()
                self.telemetry["camera"] = base64.b64encode(msg.to_jpeg_bytes(quality=65)).decode()

    def _map(self, msg):
        grid = msg.grid
        # Preserve occupied cells while reducing transfer size.
        factor = max(1, int(np.ceil(max(grid.shape) / 420)))
        if factor > 1:
            from dimos.msgs.nav_msgs.OccupancyGrid import block_max_reduce

            grid = block_max_reduce(grid, factor)
        known = int(np.count_nonzero(msg.grid >= 0))
        with self.lock:
            self.telemetry["map"] = {
                "width": grid.shape[1],
                "height": grid.shape[0],
                "resolution": msg.info.resolution * factor,
                "origin": [msg.info.origin.position.x, msg.info.origin.position.y],
                "cells": grid.ravel().tolist(),
                "known_m2": known * msg.info.resolution**2,
                "received": time.time(),
            }

    def _path(self, msg):
        with self.lock:
            self.telemetry["path"] = [[p.position.x, p.position.y] for p in msg.poses]

    @rpc
    def snapshot(self) -> dict:
        with self.lock:
            return {**self.telemetry, "recording": self.writer.state() if self.writer else None}

    @rpc
    def set_profile(self, config: dict) -> None:
        self.profile = config

    @rpc
    def begin_recording(self, path: str) -> dict:
        require(getattr(self, "profile", None) or from_env(), "recording")
        with self.lock:
            if self.writer:
                raise ValueError("A recording is already active")
            self.writer = SessionWriter(Path(path))
            return self.writer.state()

    @rpc
    def end_recording(self) -> dict:
        with self.lock:
            writer, self.writer = self.writer, None
        if writer:
            writer.close()
            return writer.state()
        return {}

    @rpc
    def stop(self):
        self.end_recording()
        super().stop()


class SessionWriter:
    def __init__(self, path: Path):
        if path.exists():
            raise ValueError("Existing recordings cannot be overwritten")
        self.path = path
        self.queue = queue.Queue(maxsize=256)
        self.counts = {}
        self.dropped = 0
        self.errors = 0
        self.error = None
        self.closed = False
        self.started = time.time()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()
        if not self.ready.wait(15) or self.error:
            raise RuntimeError(self.error or "The recorder did not respond")

    def enqueue(self, name, msg, pose):
        if self.closed or self.error:
            return
        try:
            self.queue.put_nowait((name, msg, pose, time.time()))
        except queue.Full:
            self.dropped += 1

    def _write(self):
        store = None
        try:
            store = SqliteStore(path=str(self.path))
            store.start()
            types = {
                "lidar": PointCloud2,
                "odom": PoseStamped,
                "tf": TFMessage,
                "color_image": Image,
                "camera_info": CameraInfo,
                "teleop_requested": Twist,
                "cmd_vel": Twist,
            }
            streams = {name: store.stream(name, typ) for name, typ in types.items()}
            self.ready.set()
            while (item := self.queue.get()) is not None:
                name, msg, pose, received_ts = item
                stamp = (
                    msg.transforms[0].ts
                    if name == "tf" and msg.transforms
                    else getattr(msg, "ts", None)
                )
                streams[name].append(
                    msg, ts=stamp if stamp is not None else received_ts,
                    pose=pose, tags={"reception_ts": received_ts}
                )
                self.counts[name] = self.counts.get(name, 0) + 1
        except Exception as error:
            self.errors += 1
            self.error = str(error)
            self.ready.set()
        finally:
            if store:
                store.stop()

    def close(self):
        self.closed = True
        while self.thread.is_alive():
            try:
                self.queue.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            self.error = "The recorder did not finish draining the queue"

    def state(self):
        return dict(
            path=str(self.path),
            counts=dict(self.counts),
            dropped=self.dropped,
            errors=self.errors,
            error=self.error,
            started=self.started,
            queued=self.queue.qsize(),
        )
