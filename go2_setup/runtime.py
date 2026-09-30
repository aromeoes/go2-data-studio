"""Disposable DimOS process. The console survives this process and the robot."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
import threading
import time
import zenoh

import cv2  # noqa: F401  Load before PyAV in Go2's transport.

from dimos.core.coordination.blueprints import autoconnect
from dimos.mapping.costmapper import CostMapper
from dimos.mapping.voxels.module import VoxelGridMapper
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.porcelain.dimos import Dimos

from go2_setup.modules import ConsoleBridge, ConsoleExplorer, ControlGate, PassiveGo2Connection
from go2_setup.process_guard import start_parent_guard
from go2_setup.posture import perform_posture
from go2_setup.unitree_actions import execute as execute_unitree_action
from go2_setup.navigation_status import NavigationStatus
from go2_setup.config import Settings
from go2_setup.sdk_bridge import ConsoleSDK, sdk_blueprint
from go2_setup.profiles import from_env, enabled, require


def build_blueprint(session_profile, ip="", replay=None, config=None, localization=None):
    config = config or {}
    modules = [
        PassiveGo2Connection.blueprint(ip="replay" if replay else ip, velocity_api=True),
        ControlGate.blueprint(),
        ConsoleBridge.blueprint(),
        ConsoleSDK.blueprint(),
        sdk_blueprint(),
    ]
    if enabled(session_profile, "mapping"):
        modules += [
            VoxelGridMapper.blueprint(
                device="CPU:0", voxel_size=0.1, emit_every=8, block_count=250000
            ),
            CostMapper.blueprint(),
        ]
    if localization and enabled(session_profile, "mapping"):
        from go2_setup.relocalization_module import ConsoleRelocalization, ROOM_CONFIG
        modules.append(ConsoleRelocalization.blueprint(
            map_file=localization["path"], relocalize=ROOM_CONFIG, use_carving=False,
            reloc_interval=4., relocalize_once=True, min_local_points=2000,
        ))
    if enabled(session_profile, "navigation"):
        modules.append(ReplanningAStarPlanner.blueprint())
    if enabled(session_profile, "exploration"):
        modules.append(ConsoleExplorer.blueprint())
    return autoconnect(*modules).global_config(**config)


def main():
    if os.environ.get("GO2_SUPERVISOR_PID"):
        start_parent_guard(int(os.environ["GO2_SUPERVISOR_PID"]))
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="")
    parser.add_argument("--replay")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--navigation-log")
    args = parser.parse_args()
    navigation_status = NavigationStatus(
        args.navigation_log or (None if args.replay else Settings().root / "runtime.log")
    )
    bus_endpoint = f"tcp/127.0.0.1:{20000 + args.port % 10000}"
    router_config = zenoh.Config.from_json5(
        json.dumps(
            {
                "mode": "router",
                "listen": {"endpoints": [bus_endpoint]},
                "scouting": {"multicast": {"enabled": False}, "gossip": {"enabled": False}},
            }
        )
    )
    router = zenoh.open(router_config)
    config = dict(
        n_workers=6,
        relay_url=os.environ["GO2_RELAY_URL"],
        relay_key=os.environ["GO2_RELAY_KEY"],
        robot_id="go2-space-console",
        robot_model="unitree_go2",
        robot_ip=None,
        robot_ips=None,
        zenoh_scout_addr=f"224.0.0.224:{20000 + args.port % 10000}",
        zenoh_scouting=False,
        zenoh_multicast=False,
        zenoh_mode="client",
        zenoh_connect=bus_endpoint,
    )
    if args.replay:
        config.update(replay=True, replay_db=args.replay)
    else:
        config.update(replay=False)
    session_profile = from_env()
    localization = json.loads(os.environ.get("GO2_LOCALIZATION", "null"))
    blueprint = build_blueprint(session_profile, args.ip, args.replay, config, localization)
    dimos = Dimos()
    dimos.run(blueprint)
    gate = dimos.get_module("ControlGate")
    bridge = dimos.get_module("ConsoleBridge")
    planner = (
        dimos.get_module("ReplanningAStarPlanner")
        if enabled(session_profile, "navigation")
        else None
    )
    explorer = (
        dimos.get_module("ConsoleExplorer") if enabled(session_profile, "exploration") else None
    )
    relocalizer = (dimos.get_module("ConsoleRelocalization")
                   if localization and enabled(session_profile, "mapping") else None)
    localization_done = threading.Event()
    localization_status = {"status": "loading" if relocalizer else "inactive"}

    def poll_localization():
        while not localization_done.is_set():
            try:
                current = relocalizer.state()
                ready = (current["status"] == "localized" and
                         time.time() - current.get("merged_at", 0) < 10)
                if current["status"] == "localized" and not ready:
                    current = {**current, "status": "stale", "message": "Waiting for fresh aligned map data"}
                gate.localization_state(ready)
                localization_status.update(current)
            except Exception:
                localization_status.update(status="error", message="Relocalization module is not responding")
                try:
                    gate.localization_state(False)
                except Exception:
                    pass
            localization_done.wait(.5)

    if relocalizer:
        threading.Thread(target=poll_localization, daemon=True).start()
    connection = dimos.get_module("PassiveGo2Connection")
    skills = None
    if enabled(session_profile, "humancli"):
        from go2_setup.robot_skills import RobotSkills
        skills = RobotSkills(Settings().root, gate, planner, bridge, connection, replay=bool(args.replay),
                             localization=lambda: {**(localization or {}), **localization_status})
    lock = threading.RLock()
    token = os.environ["GO2_RUNTIME_TOKEN"]

    def halt(latch=False):
        epoch = gate.halt(latch)
        if skills:
            skills.stop()
        if explorer:
            explorer.stop_exploration()
        if planner:
            planner.cancel_goal()
        return epoch

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if size > 65536:
                    raise ValueError("Request too large")
                data = json.loads(self.rfile.read(size) or b"{}")
                posture_result = None
                if self.path == "/posture":
                    posture_result = perform_posture(
                        connection, data["action"], halt, gate.state, lock, replay=bool(args.replay)
                    )
                with lock:
                    if self.path == "/state":
                        result = {
                            **bridge.snapshot(),
                            "control": gate.state(),
                            "motion": connection.motion_state(),
                            "battery": connection.battery_state(),
                            "transport": connection.transport_state(),
                            "replay": bool(args.replay),
                        }
                        result["localization"] = {**(localization or {}), **localization_status}
                        if localization_status.get("world_from_map") and result.get("pose"):
                            import numpy as np
                            from go2_setup.localization import transform_pose
                            result["localization"]["map_pose"] = transform_pose(
                                np.linalg.inv(localization_status["world_from_map"]), result["pose"])
                        result["navigation"] = navigation_status.snapshot(result)
                        result["skills"] = skills.state() if skills else None
                    elif self.path == "/localization/confirm":
                        if not relocalizer or gate.state()["mode"] != "idle":
                            raise ValueError("Pause movement before confirming localization")
                        result = relocalizer.confirm()
                    elif self.path == "/mode":
                        capability = {
                            "teleop": "teleop",
                            "explore": "exploration",
                            "agent": "humancli",
                        }.get(data["mode"])
                        if capability:
                            require(session_profile, capability)
                        halt()
                        # Clear queued velocities from the old planner mission before enabling.
                        time.sleep(0.3)
                        epoch = gate.switch(data["mode"])
                        if data["mode"] == "explore":
                            explorer.explore()
                        result = {"epoch": epoch, "mode": data["mode"]}
                    elif self.path == "/halt":
                        result = {"epoch": halt(data.get("latch", False)), "mode": "idle"}
                    elif self.path == "/release":
                        if gate.state()["epoch"] == data["epoch"]:
                            result = {"epoch": halt(), "mode": "idle", "ok": True}
                        else:
                            result = {"ok": False}
                    elif self.path == "/clear":
                        gate.clear()
                        result = {}
                    elif self.path == "/heartbeat":
                        result = {"ok": gate.heartbeat(data["epoch"])}
                    elif self.path == "/teleop":
                        result = {
                            "ok": gate.teleop(data["epoch"], data["x"], data["y"], data["yaw"])
                        }
                    elif self.path in {"/goal", "/agent/explore", "/agent/pause"}:
                        # Pausing retains the HumanCLI lease, but closes the
                        # velocity gate before cancelling either producer.
                        if not gate.navigation(data["epoch"], False):
                            raise ValueError("The instruction lost control of the robot")
                        if skills:
                            skills.stop()
                        if explorer:
                            explorer.stop_exploration()
                        if planner:
                            planner.cancel_goal()
                        result = {"ok": True, "navigation": "paused"}
                        if self.path != "/agent/pause":
                            require(
                                session_profile,
                                "exploration" if self.path == "/agent/explore" else "navigation",
                            )
                            time.sleep(0.3)
                            if not gate.navigation(data["epoch"], True):
                                raise ValueError("The instruction lost control of the robot")
                            if self.path == "/agent/explore":
                                explorer.explore()
                                result = {"ok": True, "navigation": "exploring"}
                            else:
                                result = {
                                    "ok": planner.set_goal(
                                        PoseStamped(
                                            position=[data["x"], data["y"], 0], frame_id="world"
                                        )
                                    )
                                }
                    elif self.path == "/skills/call":
                        require(session_profile, "humancli")
                        name = data["name"]
                        from go2_setup.agent_tools import TOOLS, ROBOT_SKILLS
                        if name not in ROBOT_SKILLS:
                            raise ValueError("Unknown skill")
                        schemas = {name: schema for name, schema, _, _ in TOOLS}
                        arguments = schemas[name].model_validate(data.get("arguments", {})).model_dump()
                        if name not in {"speak"}:
                            require(session_profile, "navigation")
                        if name == "follow_person":
                            require(session_profile, "camera")
                        result = skills.call(name, arguments, data["epoch"], data.get("space_id"))
                    elif self.path == "/unitree/action":
                        require(session_profile, "teleop")
                        result = execute_unitree_action(
                            connection, data["name"], control=gate.state(), epoch=data["epoch"],
                            confirmed=data["confirmed"], replay=bool(args.replay),
                        )
                    elif self.path == "/record/start":
                        result = bridge.begin_recording(data["path"])
                    elif self.path == "/record/stop":
                        result = bridge.end_recording()
                    elif self.path == "/posture":
                        result = posture_result
                    else:
                        raise ValueError("Unknown command")
                encoded = json.dumps(result).encode()
                self.send_response(200)
            except Exception as error:
                encoded = json.dumps({"error": str(error)}).encode()
                self.send_response(409)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        try:
            halt()
            bridge.end_recording()
            if skills:
                skills.close()
        finally:
            server.server_close()
            localization_done.set()
            dimos.stop()
            router.close()


if __name__ == "__main__":
    main()
