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
from go2_setup.navigation_status import NavigationStatus
from go2_setup.config import Settings
from go2_setup.sdk_bridge import ConsoleSDK, sdk_blueprint


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
    blueprint = autoconnect(
        # The planner and the UI emit m/s and rad/s, not normalized joystick axes.
        PassiveGo2Connection.blueprint(ip="replay" if args.replay else args.ip, velocity_api=True),
        VoxelGridMapper.blueprint(device="CPU:0", voxel_size=0.1, emit_every=8, block_count=250000),
        CostMapper.blueprint(),
        ReplanningAStarPlanner.blueprint(),
        ConsoleExplorer.blueprint(),
        ControlGate.blueprint(),
        ConsoleBridge.blueprint(),
        ConsoleSDK.blueprint(),
        sdk_blueprint(),
    ).global_config(**config)
    dimos = Dimos()
    dimos.run(blueprint)
    gate = dimos.get_module("ControlGate")
    bridge = dimos.get_module("ConsoleBridge")
    planner = dimos.get_module("ReplanningAStarPlanner")
    explorer = dimos.get_module("ConsoleExplorer")
    connection = dimos.get_module("PassiveGo2Connection")
    lock = threading.RLock()
    token = os.environ["GO2_RUNTIME_TOKEN"]

    def halt(latch=False):
        epoch = gate.halt(latch)
        explorer.stop_exploration()
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
                        result["navigation"] = navigation_status.snapshot(result)
                    elif self.path == "/mode":
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
                        explorer.stop_exploration()
                        planner.cancel_goal()
                        result = {"ok": True, "navigation": "paused"}
                        if self.path != "/agent/pause":
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
        finally:
            server.server_close()
            dimos.stop()
            router.close()


if __name__ == "__main__":
    main()
