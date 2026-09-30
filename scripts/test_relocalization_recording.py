"""Offline DimOS registration smoke test. Never connects to robot hardware.

Run using the bundled Python, with the application on PYTHONPATH. This tests
recovery of a planted transform relative to a baseline fit. If the map was made
from this recording, this is not an independent localization accuracy benchmark.
"""

import argparse
import copy
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np
import open3d as o3d
from dimos.mapping.relocalization.lidar.relocalize import LidarRelocalizer
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from go2_setup.relocalization_module import ROOM_CONFIG, registration_cloud
from go2_setup.localization import MatchAcceptance


def run(map_path, recording):
    cloud = PointCloud2.lcm_decode(Path(map_path).read_bytes()).pointcloud
    t0 = time.monotonic()
    matcher = LidarRelocalizer(registration_cloud(cloud), ROOM_CONFIG)
    print(json.dumps({"prepare_seconds": time.monotonic() - t0}), flush=True)
    db = sqlite3.connect(f"file:{Path(recording).resolve()}?mode=ro", uri=True)
    ids = [r[0] for r in db.execute("SELECT id FROM lidar_blob ORDER BY id")]
    assert len(ids) >= 15
    failures = []
    comparable = 0
    for offset in sorted(set([0, len(ids) // 3, max(0, 2 * len(ids) // 3 - 15)])):
        rows = db.execute(
            "SELECT data FROM lidar_blob WHERE id>=? ORDER BY id LIMIT 15", (ids[offset],)
        ).fetchall()
        scans = [PointCloud2.lcm_decode(row[0]) for row in rows]
        query = sum(scans[1:], scans[0]).pointcloud
        o3d.utility.random.seed(42)
        base = matcher.align(registration_cloud(query))
        imposed = np.eye(4)
        angle = 0.8
        imposed[:3, :3] = [
            [math.cos(angle), -math.sin(angle), 0],
            [math.sin(angle), math.cos(angle), 0],
            [0, 0, 1],
        ]
        imposed[:3, 3] = [3, -2, 0.1]
        moved = copy.deepcopy(query).transform(imposed)
        o3d.utility.random.seed(42)
        t0 = time.monotonic()
        found = matcher.align(registration_cloud(moved))
        delta = found.transformation @ imposed @ np.linalg.inv(base.transformation)
        distance = float(np.linalg.norm(delta[:3, 3]))
        rotation = math.degrees(math.acos(float(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1))))
        # A rejected baseline is not ground truth for a transform comparison.
        baseline_ok = MatchAcceptance(confirmations=1).evaluate(
            base.transformation, base.fitness, base.inlier_rmse
        )[0]
        found_ok = MatchAcceptance(confirmations=1).evaluate(
            found.transformation, found.fitness, found.inlier_rmse
        )[0]
        passed = distance < 0.25 and rotation < 5 if baseline_ok and found_ok else None
        if passed is not None:
            comparable += 1
        print(
            json.dumps(
                dict(
                    offset=offset,
                    fitness=found.fitness,
                    rmse=found.inlier_rmse,
                    seconds=time.monotonic() - t0,
                    transform_error_m=distance,
                    transform_error_deg=rotation,
                    passed=passed,
                    baseline_fitness=base.fitness,
                    outcome="comparable"
                    if passed is not None
                    else "inconclusive: matcher rejected one fit",
                )
            ),
            flush=True,
        )
        if passed is False:
            failures.append(offset)
    # A random volumetric cloud should not be accepted as this apartment.
    negative = o3d.geometry.PointCloud()
    negative.points = o3d.utility.Vector3dVector(
        np.random.default_rng(21).uniform(-15, 15, (15000, 3))
    )
    o3d.utility.random.seed(42)
    result = matcher.align(negative)
    check = MatchAcceptance(confirmations=1)
    accepted, _ = check.evaluate(result.transformation, result.fitness, result.inlier_rmse)
    print(
        json.dumps(
            dict(
                negative_control=True,
                fitness=result.fitness,
                rmse=result.inlier_rmse,
                rejected=not accepted,
            )
        ),
        flush=True,
    )
    assert not accepted and not failures and comparable >= 2, (
        f"Failed recording windows: {failures}"
    )
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map")
    parser.add_argument("recording")
    args = parser.parse_args()
    run(args.map, args.recording)
