"""Independent Vector DimOS blueprint process. Never imports the Go2 driver."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import signal
import threading
import zenoh
from dimos.core.coordination.blueprints import autoconnect
from dimos.porcelain.dimos import Dimos
from go2_setup.process_guard import start_parent_guard
from go2_setup.profiles import from_env, enabled
from go2_setup.sdk_bridge import ConsoleSDK, sdk_blueprint
from go2_setup.vector.modules import VectorConnection, VectorTelemetry, VectorSkills
from go2_setup.vector.tools import validate


def build_blueprint(profile, config=None):
    modules = [
        VectorConnection.blueprint(),
        VectorTelemetry.blueprint(),
        ConsoleSDK.blueprint(),
        sdk_blueprint(max_linear=0.12, max_angular=1.5),
    ]
    if enabled(profile, "humancli"):
        modules.append(VectorSkills.blueprint())
    return autoconnect(*modules).global_config(**(config or {}))


def main():
    if os.environ.get("GO2_SUPERVISOR_PID"):
        start_parent_guard(int(os.environ["GO2_SUPERVISOR_PID"]))
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--ip")
    parser.add_argument("--navigation-log")  # Common supervisor launch contract.
    args = parser.parse_args()
    endpoint = f"tcp/127.0.0.1:{20000 + args.port % 10000}"
    router = zenoh.open(
        zenoh.Config.from_json5(
            json.dumps(
                {
                    "mode": "router",
                    "listen": {"endpoints": [endpoint]},
                    "scouting": {"multicast": {"enabled": False}, "gossip": {"enabled": False}},
                }
            )
        )
    )
    profile = from_env()
    config = dict(
        n_workers=4,
        relay_url=os.environ["GO2_RELAY_URL"],
        relay_key=os.environ["GO2_RELAY_KEY"],
        robot_id="go2-space-console",
        robot_model="anki_vector",
        robot_ip=None,
        robot_ips=None,
        zenoh_scouting=False,
        zenoh_multicast=False,
        zenoh_mode="client",
        zenoh_connect=endpoint,
        zenoh_scout_addr=f"224.0.0.224:{20000 + args.port % 10000}",
        replay=False,
    )
    dimos = Dimos()
    dimos.run(build_blueprint(profile, config))
    connection = dimos.get_module("VectorConnection")
    telemetry = dimos.get_module("VectorTelemetry")
    skills = dimos.get_module("VectorSkills") if enabled(profile, "humancli") else None
    token = os.environ["GO2_RUNTIME_TOKEN"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if not secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 <= length <= 65536:
                    raise ValueError("Request too large")
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/state":
                    result = {
                        **telemetry.snapshot(),
                        "control": connection.control_state(),
                        "replay": False,
                    }
                elif self.path == "/vector/action":
                    if skills is None:
                        raise ValueError("HumanCLI is disabled")
                    name = data["name"]
                    arguments = validate(name, data.get("arguments", {}))
                    result = getattr(skills, name)(epoch=data["epoch"], **arguments)
                else:
                    result = connection.control(self.path, data)
                status = 200
            except Exception as error:
                result, status = {"error": str(error)}, 409
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
            connection.control("/halt", {})
        finally:
            server.server_close()
            dimos.stop()
            router.close()


if __name__ == "__main__":
    main()
