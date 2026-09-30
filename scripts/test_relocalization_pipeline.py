"""Exercise real DimOS streams with a planted map transform, without hardware.

This verifies module wiring and coordinate conventions. Using the same map as
both source and target is not independent evidence of localization accuracy.
Run from the repository with its root on PYTHONPATH and the DimOS Python runtime.
"""

import json
import time
import numpy as np
import zenoh
from dimos.porcelain.dimos import Dimos
from dimos.core.coordination.blueprints import autoconnect
from dimos.mapping.costmapper import CostMapper
from go2_setup.relocalization_module import ConsoleRelocalization, ROOM_CONFIG
from scripts.relocalization_fixture import RecordedCloudSource, CostmapObserver


def run(path):
    router = zenoh.open(
        zenoh.Config.from_json5(
            '{mode:"router",listen:{endpoints:["tcp/127.0.0.1:29092"]},scouting:{multicast:{enabled:false}}}'
        )
    )
    bp = autoconnect(
        RecordedCloudSource.blueprint(fixture=path),
        ConsoleRelocalization.blueprint(
            map_file=path, relocalize=ROOM_CONFIG, use_carving=False, reloc_interval=4.0
        ),
        CostMapper.blueprint(),
        CostmapObserver.blueprint(),
    ).global_config(
        n_workers=3,
        zenoh_mode="client",
        zenoh_connect="tcp/127.0.0.1:29092",
        zenoh_scouting=False,
        zenoh_multicast=False,
    )
    d = Dimos()
    try:
        d.run(bp)
        module = d.get_module("ConsoleRelocalization")
        observer = d.get_module("CostmapObserver")
        last = None
        for _ in range(65):
            state = module.state()
            brief = {
                k: state.get(k)
                for k in ["status", "attempts", "confirmations", "fitness", "rmse", "message"]
            }
            if brief != last:
                print(json.dumps(brief), flush=True)
                last = brief
            if state["status"] == "candidate":
                matrix = np.asarray(state["world_from_map"])
                assert np.linalg.norm(matrix[:3, 3] - [2, -3, 0]) < 0.25, matrix
                assert abs(np.arctan2(matrix[1, 0], matrix[0, 0]) - 0.5) < 0.1, matrix
                grid = observer.snapshot()
                assert grid.get("cells", 0) > 0 and grid["frame"] == "world", grid
                assert module.confirm()["ok"]
                assert module.state()["status"] == "localized"
                print(
                    "INTEGRATION PASS: candidate, planted transform, merged costmap, confirmation. No robot connection modules.",
                    flush=True,
                )
                break
            time.sleep(1)
        else:
            raise AssertionError("No candidate alignment within 65 seconds")
    finally:
        d.stop()
        router.close()


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Offline DimOS relocalization stream test. Never connects to a robot."
    )
    parser.add_argument("map", type=Path)
    args = parser.parse_args()
    run(str(args.map.resolve()))
