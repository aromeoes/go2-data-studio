import json
import time
import socket
import zenoh
from dimos.core.coordination.blueprints import autoconnect
from dimos.porcelain.dimos import Dimos
from go2_setup.vector.modules import VectorTelemetry, VectorSkills
from vector_fixture import FixtureVectorConnection


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    endpoint = f"tcp/127.0.0.1:{port}"
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
    blueprint = autoconnect(
        FixtureVectorConnection.blueprint(), VectorTelemetry.blueprint(), VectorSkills.blueprint()
    ).global_config(
        n_workers=3,
        zenoh_scouting=False,
        zenoh_multicast=False,
        zenoh_mode="client",
        zenoh_connect=endpoint,
        replay=False,
    )
    d = Dimos()
    try:
        d.run(blueprint)
        c = d.get_module("FixtureVectorConnection")
        t = d.get_module("VectorTelemetry")
        skills = d.get_module("VectorSkills")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = t.snapshot()
            if state.get("camera"):
                break
            time.sleep(0.2)
        assert state["pose"]["origin_id"] == 4 and state["camera"], state
        result = c.control("/mode", {"mode": "agent"})
        answer = skills.set_head(epoch=result["epoch"], angle_deg=15)
        assert answer["accepted"], answer
        print(
            "PASS: real DimOS workers publish camera/pose/telemetry and VectorSkills dispatch through injected RPC spec"
        )
    finally:
        d.stop()
        router.close()


if __name__ == "__main__":
    main()
