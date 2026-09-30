"""DimOS Go2 relocalization with measured status and conservative acceptance.

The matcher, accumulated voxel map, TF publication and map merge are DimOS building blocks.
The application supplies a room-scale candidate configuration and verifies repeat
matches. These settings still require validation on independent recordings.
"""

import threading
import time
from pathlib import Path

import numpy as np
from reactivex import combine_latest, operators as ops
from dimos.mapping.relocalization.module import RelocalizationModule, fix_stream
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.mapping.relocalization.lidar.relocalize import LidarRelocalizer
from dimos.utils.reactive import backpressure
from dimos.utils.logging_config import setup_logger

from dimos.core.core import rpc
from dimos.mapping.relocalization.go2.module import Go2Relocalization
from dimos.mapping.relocalization.lidar.relocalize import RelocalizeConfig
from dimos.msgs.geometry_msgs.Transform import Transform

from go2_setup.localization import MatchAcceptance

logger = setup_logger()

ROOM_CONFIG = RelocalizeConfig(
    voxel_coarse=0.3,
    voxel_fine=0.1,
    normal_radius_factor=2.0,
    fpfh_radius_factor=5.0,
    coarse_dist_factor=1.5,
    ransac_iters=200000,
    mutual_filter=True,
    edge_length=0.9,
    icp_dist_factor=1.5,
    icp_stages=3,
    orient_normals=True,
    ransac_restarts=4,
    fitness_threshold=0.90,
    min_frames=5,
    max_frames=15,
)


def registration_cloud(cloud):
    """Match structural surfaces; floor-dominated scans can fit many wrong rooms."""
    import open3d as o3d

    result = cloud.voxel_down_sample(0.1)
    result.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.3, max_nn=30))
    result = result.select_by_index(np.flatnonzero(abs(np.asarray(result.normals)[:, 2]) < 0.8))
    points = np.asarray(result.points)
    if len(points) < 500:
        raise ValueError(
            "Too few structural points. Turn slowly toward walls and corners using Teleop."
        )
    eigenvalues = np.linalg.eigvalsh(np.cov(points.T))
    if eigenvalues[0] < 0.0025 or eigenvalues[1] < 0.04:
        raise ValueError(
            "Scan geometry is too flat to distinguish a location. Try a view of a corner."
        )
    return result


class ConsoleRelocalization(Go2Relocalization):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._status_lock = threading.RLock()
        self._confirmed = False
        self._acceptance = MatchAcceptance()
        self._status = dict(
            status="loading",
            message="Loading saved map",
            attempts=0,
            confirmations=0,
            required_confirmations=3,
            world_from_map=None,
            source="accumulated_map",
        )

    def clouds(self):
        # The inherited 15-scan window forgets earlier views as the robot walks.
        # Reuse the mapper's world-frame geometry, never our merged map output.
        # This adds no second mapper and no raw-scan accumulation in this module.
        return self.global_map.observable().pipe(
            ops.throttle_first(self.config.reloc_interval)
        )

    def _load_premap(self, map_file):
        # The supervisor resolves a catalog-owned local file. Upstream get_data
        # invokes project discovery, which can hang in a packaged worker's git
        # shim. Local library maps need neither git discovery nor LFS downloads.
        path = Path(map_file)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Reference map must be an existing local library file")
        premap = PointCloud2.lcm_decode(path.read_bytes())
        premap.frame_id = self.config.map_frame
        self.premap = premap
        self.register_disposable(
            fix_stream(self.fixes, self.config.republish_loaded_map).subscribe(
                lambda _: self.loaded_map.publish(premap)
            )
        )

    @rpc
    def start(self):
        try:
            self._initialize()
        except Exception as error:
            # A bad reference map must not tear down camera and Teleop modules.
            # The control gate stays closed for saved-map autonomous navigation.
            with self._status_lock:
                self._status.update(
                    status="error", message=f"Could not load reference map: {error}"
                )

    def _initialize(self):
        # Reuse DimOS loading, voxel mapping, registration, TF and Go2 merging. Only
        # preprocessing and acceptance differ from the upstream outdoor preset.
        RelocalizationModule.start(self)
        if self.premap is None:
            return
        self._relocalizer = LidarRelocalizer(
            registration_cloud(self.premap.pointcloud), self.config.relocalize
        )
        self.register_disposable(
            backpressure(
                self.clouds().pipe(
                    ops.filter(lambda _: self.keep_relocalizing()),
                    ops.do_action(self._maybe_log_skip),
                    ops.filter(self._has_enough_points),
                )
            ).subscribe(self._relocalize)
        )
        self.register_disposable(
            backpressure(
                combine_latest(
                    self.global_map.observable(),
                    self.fixes,
                )
            ).subscribe(self._on_merge_input)
        )
        with self._status_lock:
            self._status.update(status="localizing", message="Waiting for the accumulated LiDAR map")

    @rpc
    def state(self):
        with self._status_lock:
            return {**self._status}

    def _maybe_log_skip(self, msg):
        super()._maybe_log_skip(msg)
        if not self._has_enough_points(msg):
            with self._status_lock:
                self._status.update(
                    message="Not enough LiDAR points. Wait for sensors or try a different view."
                )

    def _relocalize(self, msg):
        if not self.keep_relocalizing():
            return
        t0 = time.monotonic()
        with self._status_lock:
            self._status.update(
                status="localizing",
                message="Matching live LiDAR to the saved map",
                attempts=self._status["attempts"] + 1,
            )
        try:
            query = registration_cloud(msg.pointcloud)
            result = self._relocalizer.align(query)
            accepted, message = self._acceptance.evaluate(
                result.transformation, result.fitness, result.inlier_rmse
            )
            with self._status_lock:
                self._status.update(
                    status="verifying" if self._acceptance.count else "localizing",
                    message=message,
                    fitness=float(result.fitness),
                    rmse=float(result.inlier_rmse),
                    seconds=time.monotonic() - t0,
                    confirmations=self._acceptance.count,
                    points=len(msg),
                    structural_points=len(query.points),
                    rejection_reason=self._acceptance.reason,
                )
            # Keep candidate transforms in the runtime log, not world_from_map:
            # an unaccepted candidate must never become a navigation transform.
            logger.info(
                "relocalization_match",
                **{
                    **self.state(),
                    "candidate_map_from_world": result.transformation.tolist(),
                    "query_extent_m": np.ptp(np.asarray(query.points), axis=0).tolist(),
                },
            )
            if accepted:
                # align maps live world into saved map. DimOS publishes its inverse.
                tf = Transform.from_matrix(
                    result.transformation,
                    frame_id=self.config.map_frame,
                    child_frame_id=self.config.world_frame,
                ).inverse()
                with self._status_lock:
                    self._status.update(
                        status="merging",
                        message="Building the aligned navigation map",
                        world_from_map=tf.to_matrix().tolist(),
                    )
                self.submit(tf, "lidar")
        except Exception as error:
            self._acceptance = MatchAcceptance()
            with self._status_lock:
                self._status.update(
                    status="error", message=f"Relocalization failed: {error}", confirmations=0
                )

    def _on_merge_input(self, pair):
        try:
            # use_carving=False uses the upstream CPU pointcloud union. Old obstacles
            # remain conservative until a new map is generated; no GPU is required.
            super()._on_merge_input(pair)
            with self._status_lock:
                self._status.update(
                    status="localized" if self._confirmed else "candidate",
                    message="Localized in the saved map"
                    if self._confirmed
                    else "Match found. Check the robot position on the map, then confirm.",
                    merged_at=time.time(),
                )
        except Exception as error:
            with self._status_lock:
                self._status.update(status="error", message=f"Aligned map failed: {error}")

    @rpc
    def confirm(self):
        with self._status_lock:
            if (
                self._status["status"] != "candidate"
                or time.time() - self._status.get("merged_at", 0) > 10
            ):
                raise ValueError("Wait for a fresh candidate alignment before confirming")
            self._confirmed = True
            self._status.update(
                status="localized", message="Localized in the saved map (operator confirmed)"
            )
        return {"ok": True}
