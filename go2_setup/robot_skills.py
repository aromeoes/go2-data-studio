"""Lifecycle adapters for official DimOS skills in the application's control lease.

These objects run in the disposable runtime, using its existing DimOS planner and
sensor bridge. They do not create a second robot connection or agent harness.
Upstream skill methods are reused; storage, CPU tracking, audio routing and control
ownership are supplied here. No skill starts automatically after reconnect.
"""

import asyncio
import base64
import json
import math
import sqlite3
import threading
import time
import uuid
from types import SimpleNamespace

import cv2
import numpy as np

from dimos.agents.skills.navigation import NavigationSkillContainer
from dimos.agents.skills.person_follow import PersonFollowSkillContainer
from dimos.agents.skills.speak_skill import SpeakSkill
from dimos.core.global_config import global_config
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.navigation.patrolling.create_patrol_router import create_patrol_router
from dimos.navigation.patrolling.module import PatrollingModule
from dimos.navigation.visual_servoing.visual_servoing_2d import VisualServoing2D
from dimos.robot.unitree.go2.connection import GO2Connection
from dimos.teleop.hosted.go2_audio_bridge import (
    Go2AudioBridgeModule,
    Go2AudioBridgeConfig,
    ENTER_MEGAPHONE,
    EXIT_MEGAPHONE,
)
from dimos.types.robot_location import RobotLocation

from go2_setup.agent_settings import AgentSettings


MOTION_SKILLS = {"navigate_with_text", "start_patrol", "follow_person"}
STOP_SKILLS = {"stop_patrol", "stop_following"}


def pose_message(pose):
    return PoseStamped(
        position=[pose["x"], pose["y"], pose.get("z", 0)],
        orientation=Quaternion.from_euler(Vector3(0, 0, pose["yaw"])),
        frame_id="world",
    )


def grid_message(grid):
    return OccupancyGrid(
        grid=np.asarray(grid["cells"], dtype=np.int8).reshape(grid["height"], grid["width"]),
        resolution=grid["resolution"],
        origin=Pose(position=[*grid["origin"], 0]),
        frame_id="world",
    )


def clear_footprint(grid, x, y, radius=0.3):
    resolution = grid["resolution"]
    if not resolution > 0:
        return False
    r = math.ceil(radius / resolution)
    col = math.floor((x - grid["origin"][0]) / resolution)
    row = math.floor((y - grid["origin"][1]) / resolution)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            cx, cy = col + dx, row + dy
            if not (0 <= cx < grid["width"] and 0 <= cy < grid["height"]):
                return False
            if grid["cells"][cy * grid["width"] + cx] != 0:
                return False
    return True


def follow_corridor_clear(snapshot, x, yaw):
    """Conservative short swept footprint; unknown cells stop visual servoing."""
    now = time.time()
    grid, pose = snapshot.get("map"), snapshot.get("pose")
    if not grid or not pose or now - grid.get("received", 0) > 2:
        return False
    for name in ("odom", "lidar", "color_image"):
        if now - snapshot.get("sensors", {}).get(name, {}).get("received", 0) > 1:
            return False
    # Cover a 1.5 second stopping horizon plus the robot footprint, including turns.
    radius = 0.4 if abs(yaw) > 0.05 else 0.3
    for t in np.linspace(0, 1.5, 12):
        angle = pose["yaw"] + yaw * t / 2
        if not clear_footprint(
            grid, pose["x"] + x * t * math.cos(angle), pose["y"] + x * t * math.sin(angle), radius
        ):
            return False
    return True


class Places:
    """Persistent names scoped to a space AND this odometry frame's lifetime."""

    def __init__(self, root, frame, localization=None):
        self.localization = localization or (lambda: {})
        self.path = root / "named-places.sqlite"
        self.frame, self.space, self.yaw = frame, None, 0
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS places (space TEXT, name TEXT, frame TEXT, pose TEXT, PRIMARY KEY(space,name))"
            )

    def anchor(self):
        state = self.localization()
        if not state.get("id"):
            return self.frame, None
        if state.get("status") != "localized" or self.space != state.get("space_id"):
            raise ValueError("Select the matching space and wait for saved-map relocalization")
        return "map:" + state["id"] + ":" + state["fingerprint"], np.asarray(state["world_from_map"])

    def tag_location(self, location):
        if not self.space:
            raise ValueError("Select a space before tagging a location")
        frame, world_from_map = self.anchor()
        pose = dict(x=location.position[0], y=location.position[1], z=location.position[2], yaw=self.yaw)
        if world_from_map is not None:
            from go2_setup.localization import transform_pose
            pose = transform_pose(np.linalg.inv(world_from_map), pose)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR REPLACE INTO places VALUES (?,?,?,?)",
                (
                    self.space,
                    location.name.strip().casefold(),
                    frame,
                    json.dumps(
                        {
                            "name": location.name.strip(),
                            "position": [pose["x"], pose["y"], pose["z"]],
                            "rotation": [0, 0, pose["yaw"]],
                        }
                    ),
                ),
            )
        return True

    def query_tagged_location(self, name):
        if not self.space:
            raise ValueError("Select the space containing the named location")
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT frame,pose FROM places WHERE space=? AND name=?",
                (self.space, name.strip().casefold()),
            ).fetchone()
        if row is None:
            return None
        frame, world_from_map = self.anchor()
        if row[0] != frame:
            raise ValueError(
                "This place belongs to an earlier connection. Saved-map relocalization is not active. Tag it again in this session before navigating."
            )
        value = json.loads(row[1])
        if world_from_map is not None:
            from go2_setup.localization import transform_pose
            pose = transform_pose(world_from_map, dict(x=value["position"][0], y=value["position"][1],
                                                      z=value["position"][2], yaw=value["rotation"][2]))
            value.update(position=[pose["x"], pose["y"], pose["z"]], rotation=[0, 0, pose["yaw"]])
        return RobotLocation(**value)

    def query_by_text(self, query):
        return []  # No semantic image database is configured in this product.

    def list(self):
        try:
            current_frame, _ = self.anchor()
        except ValueError:
            current_frame = None
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT frame,pose FROM places WHERE space=? ORDER BY name", (self.space,)
            ).fetchall()
        return [
            {"name": json.loads(pose)["name"], "usable": frame == current_frame}
            for frame, pose in rows
        ]


class NamedNavigation(NavigationSkillContainer):
    """Reuse DimOS tag/query skills without constructing an unused Qwen model.

    The app owns the lifecycle; this adapter is not separately registered as a
    DimOS module. The existing runtime planner remains the navigation module.
    """

    def __init__(self, owner):
        self.owner = owner
        self._spatial_memory = owner.places
        self._skill_started = True
        self._object_tracking = None
        self._latest_odom = None

    def _navigate_to(self, pose, message):
        # Tags were checked against this frame by Places. The upstream tagged
        # path labels them 'map'; here they are explicitly in this live world.
        pose.frame_id = "world"
        if not self.owner.send_goal(pose):
            raise ValueError("The planner refused the named location")
        return message + " Navigation accepted; arrival is not confirmed."


class Patrol(PatrollingModule):
    """Run the official patrol coroutine with the app's guarded planner adapter."""

    def __init__(self, owner):
        self.owner = owner
        self.generation = getattr(owner, "generation", 0)
        self._loop = owner.loop if hasattr(owner, "loop") else asyncio.get_running_loop()
        self._global_config = global_config
        self._router = create_patrol_router("coverage", max(0.4, global_config.robot_width * 0.5))
        self._router._occupancy_grid_min_update_interval_s = 2.0
        self._goal_reached_event = asyncio.Event()
        self._patrol_task = None
        self._latest_pose = None
        self._planner_spec = owner.planner
        self.goal_request = SimpleNamespace(publish=self._publish_goal)

    def _publish_goal(self, pose):
        # DimOS's patrol utility leaves frame_id empty. Its coordinates come
        # from the live world-frame grid that we supplied to the router.
        pose.frame_id = "world"
        if getattr(self.owner, "generation", 0) != self.generation:
            raise ValueError("Patrol was cancelled")
        return self.owner.send_goal(pose)

    async def begin(self, snapshot):
        result = await self.start_patrol()
        # start_patrol resets its router; seed it after reset, before the task
        # starts selecting goals. Subsequent snapshots keep the map current.
        await self.handle_odom(pose_message(snapshot["pose"]))
        await self.handle_global_costmap(grid_message(snapshot["map"]))
        self._planner_spec.set_replanning_enabled(True)
        return result

    def start_tool(self, *args):
        pass  # The browser's control epoch owns the movement lease.

    def stop_tool(self, *args):
        pass

    async def _stop_patrolling(self):
        # Upstream publishes a current-pose goal on stop. The app cancels the
        # planner after closing its gate instead, avoiding a late stop goal.
        task, self._patrol_task = self._patrol_task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._planner_spec.set_replanning_enabled(True)
        self._planner_spec.reset_safe_goal_clearance()


class Detection:
    def __init__(self, bbox):
        self.bbox = bbox

    def bbox_2d_volume(self):
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)


class Detections:
    def __init__(self, bbox=None):
        self.detections = [] if bbox is None else [Detection(bbox)]

    def __len__(self):
        return len(self.detections)


class CPUTracker:
    """OpenCV CSRT implementing the track interface used by DimOS follow_person."""

    def __init__(self):
        self.tracker = None
        self.image = None
        self.result = Detections()

    def init_track(self, image, box, obj_id=1):
        h, w = image.data.shape[:2]
        x1, y1, x2, y2 = map(float, box)
        if (
            not all(math.isfinite(v) for v in box)
            or not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h)
            or min(x2 - x1, y2 - y1) < 8
        ):
            raise ValueError("Person detector returned an invalid pixel bounding box")
        self.tracker = cv2.TrackerCSRT_create()
        self.tracker.init(image.data, (int(x1), int(y1), int(x2 - x1), int(y2 - y1)))
        self.image, self.result = image, Detections((x1, y1, x2, y2))
        return self.result

    def process_image(self, image):
        if image is self.image:
            return self.result
        ok, box = self.tracker.update(image.data)
        self.image = image
        x, y, w, h = box
        self.result = Detections((x, y, x + w, y + h)) if ok else Detections()
        return self.result

    def stop(self):
        self.tracker = None


class Follow(PersonFollowSkillContainer):
    """Official person-follow loop with CPU tracking and a guarded velocity sink."""

    def __init__(self, owner):
        self.owner = owner
        self.config = SimpleNamespace(use_3d_navigation=False)
        self._latest_image = None
        self._lock = threading.RLock()
        self._thread = None
        self._should_stop = threading.Event()
        self._tracker = CPUTracker()
        self._frequency = 8.0
        self._max_lost_frames = 4
        self._camera_info = GO2Connection.camera_info_static
        self._visual_servo = VisualServoing2D(self._camera_info, False)
        self.cmd_vel = SimpleNamespace(
            publish=lambda twist: owner.send_follow_velocity(self, twist)
        )

    def start_tool(self, *args):
        pass

    def stop_tool(self, *args):
        pass

    def tool_update(self, name, message):
        self.owner.update(message=message)

    def _follow_loop(self, tracker, query):
        try:
            super()._follow_loop(tracker, query)
        except Exception:
            self.owner.update(
                phase="error",
                message="Person tracking stopped. No movement will resume automatically.",
            )
        finally:
            self._should_stop.set()
            self.cmd_vel.publish(Twist.zero())


class RobotSpeech(SpeakSkill):
    """DimOS TTS routed to the existing Go2 connection, with checked completion."""

    def __init__(self, owner):
        self.owner = owner
        self.generation = owner.generation
        self.cancel = owner.cancel_event
        self._tts_node = None

    def check(self):
        if self.generation != self.owner.generation or self.cancel.is_set():
            raise ValueError("Speech cancelled")
        self.owner.require_active(movement=False)

    def request(self, topic, data):
        with self.owner.lock:
            self.check()
            return self.owner.audio_request(topic, data)

    def speak(self, text, blocking=True):
        # Override upstream's text-emitted completion, which precedes audio.
        from dimos.stream.audio.tts.node_openai import OpenAITTSNode, Voice

        cfg = self.owner.openai_config(vision=False)
        node = OpenAITTSNode(api_key=cfg["api_key"], voice=Voice.ONYX)
        event, frames = threading.Event(), []
        subscription = node.emit_audio().subscribe(
            lambda frame: (frames.append(frame), event.set())
        )
        self._tts_node = node
        try:
            worker = threading.Thread(target=node._synthesize_speech, args=(text,), daemon=True)
            worker.start()
            if not event.wait(40):
                raise ValueError(
                    "Speech synthesis did not return audio. Check OpenAI settings and quota."
                )
            self.check()
            bridge = object.__new__(Go2AudioBridgeModule)
            bridge.config = Go2AudioBridgeConfig(chunk_interval_sec=0.01)
            bridge._stop_event = self.cancel
            bridge.go2 = SimpleNamespace(publish_request=self.request)
            bridge._megaphone_active = False
            try:
                bridge._request(ENTER_MEGAPHONE)
                bridge._megaphone_active = True
                self.cancel.wait(0.2)
                pcm = bridge._to_mono_target_rate(frames[0])
                bridge._upload_wav(bridge._wav_bytes(pcm))
                # Unitree buffers the uploaded clip. Keep its speaker route open
                # for the clip duration, then close it even on cancellation.
                self.cancel.wait(min(40, len(pcm) / 44100 + 0.5))
                self.check()
            finally:
                if bridge._megaphone_active:
                    # Cleanup is allowed after cancellation; it cannot move Go2.
                    from unitree_webrtc_connect.constants import RTC_TOPIC

                    self.owner.connection.publish_request(
                        RTC_TOPIC["AUDIO_HUB_REQ"], {"api_id": EXIT_MEGAPHONE, "parameter": "{}"}
                    )
            return "Speech audio sent to the Go2 speaker; audibility is not confirmed."
        finally:
            subscription.dispose()
            node.dispose()
            self._tts_node = None


class RobotSkills:
    def __init__(self, root, gate, planner, bridge, connection, replay=False, localization=None):
        self.gate, self.planner, self.bridge, self.connection = gate, planner, bridge, connection
        self.replay = replay
        self.lock = threading.RLock()
        self.frame = uuid.uuid4().hex
        self.places = Places(root, self.frame, localization)
        self.config = AgentSettings(root)
        self.epoch = None
        self.generation = 0
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.status = {
            "active": None,
            "phase": "idle",
            "message": "Ready. Named places use the current connection's map frame.",
        }
        self.snapshot = {}
        self.follow = None
        self.patrol = None
        self.last_goal = 0
        self.goal_seen_active = False
        self.last_grid = None
        self.worker = None
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.loop_thread.start()
        self.poller = threading.Thread(target=self._poll, daemon=True)
        self.poller.start()

    def update(self, **values):
        with self.lock:
            self.status.update(values)

    def state(self):
        with self.lock:
            return {
                **self.status,
                "places": self.places.list(),
                "frame": self.frame,
                "follow_tracker": "OpenCV CSRT (CPU)",
                "speech_output": "Go2 speaker",
            }

    def require_active(self, movement=True):
        state = self.gate.state()
        if (
            self.cancel_event.is_set()
            or state["epoch"] != self.epoch
            or state["mode"] != "agent"
            or state["estop"]
        ):
            raise ValueError("The skill lost control. Send a new instruction.")
        if movement and not state["navigation_enabled"]:
            raise ValueError("Navigation is paused")

    def openai_config(self, vision=True):
        # Settings can change while the disposable runtime is still connected.
        with self.config.lock:
            if self.config.path.exists():
                self.config.values = json.loads(self.config.path.read_text())
            cfg = self.config.resolve()
        if cfg["provider"] != "openai" or cfg["base_url"] or not cfg["api_key"]:
            raise ValueError(
                "This skill requires an OpenAI key at the default endpoint in HumanCLI settings"
            )
        if vision and not cfg["vision"]:
            raise ValueError("Enable vision in HumanCLI settings to identify the person")
        return cfg

    def send_goal(self, pose):
        with self.lock:
            self.require_active()
            grid = self.snapshot.get("map")
            if not grid or not clear_footprint(grid, pose.position.x, pose.position.y):
                raise ValueError("The destination is outside known clear space")
            if pose.frame_id != "world":
                raise ValueError("The goal is not aligned with this connection's map")
            if not self.planner.set_goal(pose):
                raise ValueError("The planner refused the destination")
            self.last_goal = time.monotonic()
            self.goal_seen_active = False
            self.status.update(
                phase="navigating",
                message="Navigating to the next destination.",
                goal={"x": pose.position.x, "y": pose.position.y},
            )
            return True

    def send_follow_velocity(self, follower, twist):
        with self.lock:
            if follower is not self.follow:
                return
            try:
                self.require_active()
            except ValueError:
                return
            x = max(-0.2, min(0.3, twist.linear.x))
            yaw = max(-0.4, min(0.4, twist.angular.z))
            if not follow_corridor_clear(self.snapshot, x, yaw):
                x = yaw = 0
                self.status.update(
                    phase="blocked",
                    message="Following paused: fresh camera, position and a clear mapped corridor are required.",
                )
            elif not self.follow._should_stop.is_set():
                self.status.update(
                    phase="following",
                    message="Following the selected person using the CPU tracker.",
                )
            self.gate.skill_velocity(self.epoch, x, 0, yaw)

    def audio_request(self, topic, data):
        self.require_active(movement=False)
        if self.replay:
            raise ValueError("Robot speaker playback is unavailable in replay")
        response = self.connection.publish_request(topic, data)
        if Go2AudioBridgeModule._response_code(response) != 0:
            raise ValueError(
                "Go2 did not acknowledge the speaker request. Audio may be unsupported by this model or firmware."
            )
        return response

    def stop(self, message="Skills stopped."):
        # Caller closes the velocity gate FIRST. Invalidate delayed VLM/TTS work.
        self.cancel_event.set()
        with self.lock:
            self.generation += 1
            follow, patrol = self.follow, self.patrol
            self.follow, self.patrol = None, None
            self.status.update(active=None, phase="idle", message=message)
        if follow:
            follow._should_stop.set()
            if follow._thread:
                follow._thread.join(timeout=2)
                if follow._thread.is_alive():
                    raise ValueError("Person tracking is still stopping")
        if patrol:
            asyncio.run_coroutine_threadsafe(patrol._stop_patrolling(), self.loop).result(timeout=5)
        self.last_goal = 0
        self.last_grid = None
        if self.planner:
            self.planner.cancel_goal()

    def call(self, name, arguments, epoch, space_id=None):
        state = self.gate.state()
        if state["epoch"] != epoch or state["mode"] != "agent" or state["estop"]:
            raise ValueError("The skill belongs to an expired HumanCLI session")
        if name in {"tag_location", "list_locations"}:
            with self.lock:
                if self.status["active"] and space_id != self.places.space:
                    raise ValueError("Stop the current skill before changing its space")
                self.places.space = space_id
                if name == "list_locations":
                    return {"ok": True, "locations": self.places.list()}
                snap = self.bridge.snapshot()
                if time.time() - snap.get("sensors", {}).get("odom", {}).get("received", 0) > 1:
                    raise ValueError("Wait for a fresh robot position before tagging")
                self.places.yaw = snap["pose"]["yaw"]
                navigation = NamedNavigation(self)
                navigation._latest_odom = pose_message(snap["pose"])
                return {"ok": True, "message": navigation.tag_location(arguments["location_name"])}
        if name in STOP_SKILLS:
            self.gate.navigation(epoch, False)
            self.stop()
            return {"ok": True, "message": "Navigation and following stopped."}
        if name not in MOTION_SKILLS | {"speak"}:
            raise ValueError("Unknown skill")
        if self.status["active"] or state["navigation_enabled"]:
            raise ValueError("Stop the current navigation or skill before starting another")
        if self.worker and self.worker.is_alive():
            raise ValueError("The previous skill is still finishing. Wait before starting another.")
        self.generation += 1
        self.cancel_event = threading.Event()
        self.epoch = epoch
        self.places.space = space_id
        self.snapshot = self.bridge.snapshot()
        if name in MOTION_SKILLS:
            if not self.gate.navigation(epoch, True):
                raise ValueError("The skill lost the HumanCLI control lease")
        self.update(
            active=name, phase="starting", message="Starting " + name.replace("_", " ") + "."
        )
        generation = self.generation
        self.worker = threading.Thread(
            target=self._run, args=(name, arguments, generation), daemon=True
        )
        self.worker.start()
        return {
            "ok": True,
            "accepted": True,
            "completed": False,
            "message": "Skill requested. Check robot_status for progress and errors.",
        }

    def _run(self, name, arguments, generation):
        try:
            if name == "speak":
                if self.replay:
                    raise ValueError("Robot speaker playback is unavailable in replay")
                message = RobotSpeech(self).speak(arguments["text"])
                with self.lock:
                    if generation == self.generation:
                        self.update(active=None, phase="complete", message=message)
                return
            if name == "follow_person":
                cfg = self.openai_config()
                self.require_active()
                image = self._image(self.snapshot)
                from dimos.models.vl.openai import OpenAIVlModel
                from dimos.navigation.visual.query import get_object_bbox_from_image

                model = OpenAIVlModel(api_key=cfg["api_key"], model_name=cfg["model"])
                try:
                    bbox = get_object_bbox_from_image(
                        model,
                        image,
                        arguments["query"]
                        + ". Return pixel coordinates in this image, not normalized coordinates. Select only a person; return null if ambiguous.",
                    )
                finally:
                    model.stop()
                if bbox is None:
                    raise ValueError("Could not identify one matching person in the camera")
                with self.lock:
                    self._check_generation(generation)
                    self.openai_config()  # Recheck vision consent after detection.
                    self.follow = Follow(self)
                    self.follow._latest_image = image
                    # Real DimOS follow_person method, with the precomputed box.
                    message = self.follow.follow_person(arguments["query"], initial_bbox=list(bbox))
                    self.update(message=message)
                return
            with self.lock:
                self._check_generation(generation)
                if name == "navigate_with_text":
                    navigation = NamedNavigation(self)
                    message = navigation.navigate_with_text(arguments["query"])
                    if not self.last_goal:
                        raise ValueError(
                            "No current-session place matches this name. Use list_locations or tag_location first. Visual object navigation and saved-map relocalization are not active."
                        )
                    self.update(message=message)
                elif name == "start_patrol":
                    self.patrol = Patrol(self)
                    self.patrol._latest_pose = pose_message(self.snapshot["pose"])
                    self.patrol._router.handle_odom(self.patrol._latest_pose)
                    self.patrol._router.handle_occupancy_grid(grid_message(self.snapshot["map"]))
                    self.last_grid = None
                    self.patrol_start = asyncio.run_coroutine_threadsafe(
                        self.patrol.begin(self.snapshot), self.loop
                    )
                    self.update(
                        phase="choosing",
                        message="Choosing a patrol destination in known clear space. If none is available, map a larger connected area with Teleop.",
                    )
        except Exception as error:
            with self.lock:
                if generation != self.generation:
                    return
                self.cancel_event.set()
                if self.follow:
                    self.follow._should_stop.set()
                if self.patrol:
                    asyncio.run_coroutine_threadsafe(self.patrol._stop_patrolling(), self.loop)
                self.gate.navigation(self.epoch, False)
                if self.planner:
                    self.planner.cancel_goal()
                self.status.update(
                    active=None,
                    phase="error",
                    message=str(error)
                    if isinstance(error, ValueError)
                    else "Skill failed. Check the runtime log; no movement will resume automatically.",
                )

    def _check_generation(self, generation):
        if generation != self.generation:
            raise ValueError("The skill was cancelled")
        self.require_active()

    @staticmethod
    def _image(snapshot):
        if time.time() - snapshot.get("sensors", {}).get("color_image", {}).get("received", 0) > 1:
            raise ValueError("Wait for a fresh camera image")
        raw = cv2.imdecode(
            np.frombuffer(base64.b64decode(snapshot["camera"]), dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if raw is None:
            raise ValueError("Camera image could not be decoded")
        return Image(data=raw, format=ImageFormat.BGR)

    def _poll(self):
        last_camera = 0
        while not self.done.wait(0.15):
            try:
                snap = self.bridge.snapshot()
                with self.lock:
                    self.snapshot = snap
                    if not self.status["active"]:
                        continue
                    state = self.gate.state()
                    expired = (
                        state["epoch"] != self.epoch or state["mode"] != "agent" or state["estop"]
                    )
                if expired:
                    self.stop("Skill stopped because control changed or expired.")
                    continue
                if self.follow:
                    camera_ts = snap.get("sensors", {}).get("color_image", {}).get("received", 0)
                    if camera_ts != last_camera:
                        self.follow._on_color_image(self._image(snap))
                        last_camera = camera_ts
                    if self.follow._thread and not self.follow._thread.is_alive():
                        self.gate.navigation(self.epoch, False)
                        self.stop("Person following ended. Send a new instruction to follow again.")
                if self.patrol:
                    patrol = self.patrol

                    async def feed(patrol=patrol, snap=snap):
                        await patrol.handle_odom(pose_message(snap["pose"]))
                        stamp = snap["map"].get("received")
                        if stamp != self.last_grid:
                            await patrol.handle_global_costmap(grid_message(snap["map"]))
                            self.last_grid = stamp

                    asyncio.run_coroutine_threadsafe(feed(), self.loop).result(timeout=3)
                    if self.patrol_start.done() and self.patrol_start.exception():
                        raise ValueError(
                            "Patrol could not start: " + str(self.patrol_start.exception())
                        )
                    task = patrol._patrol_task
                    if task and task.done():
                        error = task.exception()
                        raise ValueError(str(error) if error else "Patrol ended")
                if self.last_goal:
                    reached = self.planner.is_goal_reached()
                    if not reached:
                        self.goal_seen_active = True
                    if reached and self.goal_seen_active:
                        self.last_goal = 0
                        if self.patrol:
                            self.loop.call_soon_threadsafe(self.patrol._goal_reached_event.set)
                            self.update(
                                phase="choosing",
                                message="Destination reached. Choosing the next patrol goal.",
                            )
                        else:
                            self.gate.navigation(self.epoch, False)
                            self.update(
                                active=None, phase="complete", message="Destination reached."
                            )
                    elif time.monotonic() - self.last_goal > 90:
                        raise ValueError(
                            "Destination was not reached within 90 seconds. Patrol/navigation paused."
                        )
            except Exception as error:
                if self.status.get("active"):
                    try:
                        self.gate.navigation(self.epoch, False)
                        self.stop()
                        if self.planner:
                            self.planner.cancel_goal()
                    finally:
                        self.update(
                            phase="error",
                            message=str(error)
                            if isinstance(error, ValueError)
                            else "Skill stopped because sensor or planner status could not be read.",
                        )

    def close(self):
        self.done.set()
        self.stop()
        self.poller.join(timeout=3)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(timeout=3)
        self.loop.close()
