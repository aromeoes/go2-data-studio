"""Offline fixture modules. No hardware transport or robot commands."""

import threading
from pathlib import Path
from dimos.core.module import Module, ModuleConfig
from dimos.core.core import rpc
from dimos.core.stream import Out, In
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.geometry_msgs.Transform import Transform
import numpy as np


class FixtureConfig(ModuleConfig):
    fixture: str = ""


class RecordedCloudSource(Module):
    config: FixtureConfig
    lidar: Out[PointCloud2]
    global_map: Out[PointCloud2]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.done = threading.Event()

    @rpc
    def start(self):
        super().start()
        cloud = PointCloud2.lcm_decode(Path(self.config.fixture).read_bytes())
        cloud.frame_id = "world"
        a = 0.5
        matrix = np.array(
            [
                [np.cos(a), -np.sin(a), 0, 2],
                [np.sin(a), np.cos(a), 0, -3],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        )
        self.cloud = cloud.transform(
            Transform.from_matrix(matrix, frame_id="world", child_frame_id="world")
        )

        def loop():
            while not self.done.wait(0.25):
                self.lidar.publish(self.cloud)
                self.global_map.publish(self.cloud)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    @rpc
    def stop(self):
        self.done.set()
        if hasattr(self, "thread"):
            self.thread.join(2)
        super().stop()


class CostmapObserver(Module):
    global_costmap: In[OccupancyGrid]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last = {}

    @rpc
    def start(self):
        super().start()
        self.global_costmap.subscribe(
            lambda m: setattr(self, "last", {"frame": m.frame_id, "cells": int(m.grid.size)})
        )

    @rpc
    def snapshot(self):
        return self.last
