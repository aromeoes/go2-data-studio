"""Disposable DimOS process. The console survives this process and the robot."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
import threading
import time
from types import SimpleNamespace
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


# Session modules that are separate DimOS modules, in the order they must start.
# The others in the catalog are part of the base connection or app services.
EXTRA_MODULES = {
    "VoxelGridMapper": lambda: VoxelGridMapper.blueprint(
        device="CPU:0", voxel_size=0.1, emit_every=8, block_count=250000
    ),
    "CostMapper": lambda: CostMapper.blueprint(),
    "ReplanningAStarPlanner": lambda: ReplanningAStarPlanner.blueprint(),
    "WavefrontFrontierExplorer": lambda: ConsoleExplorer.blueprint(),
}
LEGACY_EXTRAS = {
    "mapping": ["VoxelGridMapper", "CostMapper"],
    "navigation": ["ReplanningAStarPlanner"],
    "exploration": ["WavefrontFrontierExplorer"],
}


def extra_modules(session_profile):
    """Extra DimOS modules a profile needs. Profiles without a module list use capabilities."""
    if session_profile.get("modules") is not None:
        wanted = set(session_profile["modules"])
    else:
        wanted = {
            m for capability, ids in LEGACY_EXTRAS.items() if enabled(session_profile, capability) for m in ids
        }
    return [m for m in EXTRA_MODULES if m in wanted]


def build_blueprint(session_profile, ip="", replay=None, config=None):
    config = config or {}
    modules = [
        PassiveGo2Connection.blueprint(ip="replay" if replay else ip, velocity_api=True),
        ControlGate.blueprint(),
        ConsoleBridge.blueprint(),
        ConsoleSDK.blueprint(),
        sdk_blueprint(),
    ] + [EXTRA_MODULES[m]() for m in extra_modules(session_profile)]
    return autoconnect(*modules).global_config(**config)


def added_modules(current, new):
    """Modules to deploy when a session grows from `current` to `new`. Never removes any."""
    missing = [c for c in current["enabled"] if c not in new["enabled"]]
    if missing:
        raise ValueError("Modules cannot be removed from a running session")
    if current.get("modules") is not None and new.get("modules") is not None:
        removed = [m for m in current["modules"] if m not in new["modules"]]
        if removed:
            raise ValueError("Modules cannot be removed from a running session")
    have = set(extra_modules(current))
    return [m for m in extra_modules(new) if m not in have]


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
    blueprint = build_blueprint(from_env(), args.ip, args.replay, config)
    dimos = Dimos()
    dimos.run(blueprint)
    gate = dimos.get_module("ControlGate")
    bridge = dimos.get_module("ConsoleBridge")
    connection = dimos.get_module("PassiveGo2Connection")
    # Modules can be added while connected, so their handles live here.
    rt = SimpleNamespace(profile=from_env(), planner=None, explorer=None, skills=None, loading=False)

    def attach(session_profile):
        rt.profile = session_profile
        gate.set_profile(session_profile)
        bridge.set_profile(session_profile)
        if enabled(session_profile, "navigation") and rt.planner is None:
            rt.planner = dimos.get_module("ReplanningAStarPlanner")
        if enabled(session_profile, "exploration") and rt.explorer is None:
            rt.explorer = dimos.get_module("ConsoleExplorer")
        if enabled(session_profile, "humancli") and rt.skills is None:
            from go2_setup.robot_skills import RobotSkills

            rt.skills = RobotSkills(
                Settings().root, gate, rt.planner, bridge, connection, replay=bool(args.replay)
            )

    attach(rt.profile)
    lock = threading.RLock()
    token = os.environ["GO2_RUNTIME_TOKEN"]

    def halt(latch=False):
        epoch = gate.halt(latch)
        if rt.skills:
            rt.skills.stop()
        if rt.explorer:
            rt.explorer.stop_exploration()
        if rt.planner:
            rt.planner.cancel_goal()
        return epoch

    def add_modules(new_profile):
        """Deploy only the missing modules into the running coordinator."""
        with lock:
            if rt.loading:
                raise ValueError("Modules are already loading")
            added = added_modules(rt.profile, new_profile)
            halt()
            rt.loading = True
        try:
            # Not under `lock`: state requests keep answering while modules start.
            if added:
                dimos.run(autoconnect(*[EXTRA_MODULES[m]() for m in added]))
            with lock:
                attach(new_profile)
            return {"ok": True, "added": added}
        finally:
            rt.loading = False

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
                # Nothing may move the robot while modules start.
                if rt.loading and self.path not in {"/state", "/halt", "/modules"}:
                    raise ValueError("Modules are loading. Wait a moment.")
                posture_result = None
                if self.path == "/posture":
                    posture_result = perform_posture(
                        connection, data["action"], halt, gate.state, lock, replay=bool(args.replay)
                    )
                if self.path == "/modules":
                    from go2_setup.profiles import profile

                    result = add_modules(profile(**data["profile"]))
                    self._reply(200, result)
                    return
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
                        result["navigation"] = navigation_status.snapshot(result)
                        result["skills"] = rt.skills.state() if rt.skills else None
                        result["loading_modules"] = rt.loading
                    elif self.path == "/mode":
                        capability = {
                            "teleop": "teleop",
                            "explore": "exploration",
                            "agent": "humancli",
                        }.get(data["mode"])
                        if capability:
                            require(rt.profile, capability)
                        halt()
                        # Clear queued velocities from the old planner mission before enabling.
                        time.sleep(0.3)
                        epoch = gate.switch(data["mode"])
                        if data["mode"] == "explore":
                            rt.explorer.explore()
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
                    elif self.path == "/hold":
                        if data.get("on"):
                            halt()
                        gate.set_hold(bool(data.get("on")))
                        result = {"ok": True, "hold": bool(data.get("on"))}
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
                        if rt.skills:
                            rt.skills.stop()
                        if rt.explorer:
                            rt.explorer.stop_exploration()
                        if rt.planner:
                            rt.planner.cancel_goal()
                        result = {"ok": True, "navigation": "paused"}
                        if self.path != "/agent/pause":
                            require(
                                rt.profile,
                                "exploration" if self.path == "/agent/explore" else "navigation",
                            )
                            time.sleep(0.3)
                            if not gate.navigation(data["epoch"], True):
                                raise ValueError("The instruction lost control of the robot")
                            if self.path == "/agent/explore":
                                rt.explorer.explore()
                                result = {"ok": True, "navigation": "exploring"}
                            else:
                                result = {
                                    "ok": rt.planner.set_goal(
                                        PoseStamped(
                                            position=[data["x"], data["y"], 0], frame_id="world"
                                        )
                                    )
                                }
                    elif self.path == "/skills/call":
                        require(rt.profile, "humancli")
                        name = data["name"]
                        from go2_setup.agent_tools import TOOLS, ROBOT_SKILLS
                        if name not in ROBOT_SKILLS:
                            raise ValueError("Unknown skill")
                        schemas = {name: schema for name, schema, _, _ in TOOLS}
                        arguments = schemas[name].model_validate(data.get("arguments", {})).model_dump()
                        from go2_setup.agent_tools import SKILL_MODULES
                        from go2_setup.blueprints import has_module

                        if not has_module(rt.profile, SKILL_MODULES.get(name, "")):
                            raise ValueError(f"{SKILL_MODULES.get(name)} is not part of this session")
                        if name not in {"speak"}:
                            require(rt.profile, "navigation")
                        if name == "follow_person":
                            require(rt.profile, "camera")
                        result = rt.skills.call(name, arguments, data["epoch"], data.get("space_id"))
                    elif self.path == "/unitree/action":
                        from go2_setup.blueprints import has_module

                        require(rt.profile, "teleop")
                        if not has_module(rt.profile, "UnitreeSkillContainer"):
                            raise ValueError("UnitreeSkillContainer is not part of this session")
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
                self._reply(200, result)
            except Exception as error:
                self._reply(409, {"error": str(error)})

        def _reply(self, status, result):
            encoded = json.dumps(result).encode()
            self.send_response(status)
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
            if rt.skills:
                rt.skills.close()
        finally:
            server.server_close()
            dimos.stop()
            router.close()


if __name__ == "__main__":
    main()
