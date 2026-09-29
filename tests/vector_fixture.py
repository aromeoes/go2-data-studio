"""Synthetic Vector driver for exercising real DimOS process boundaries."""

import threading
import time
from types import SimpleNamespace
from concurrent.futures import Future
from PIL import Image as PILImage
from dimos.core.module import Module
from go2_setup.vector.modules import VectorConnection
from go2_setup.vector.control import VectorController
from go2_setup.profiles import profile


class FixtureDriver:
    def __init__(self):
        self.triggers = set()
        self.latest_image = None
        self.robot = SimpleNamespace(camera=SimpleNamespace(latest_image=None))

    def connect(self):
        pass

    def close(self):
        pass

    def acquire(self):
        pass

    def release(self):
        pass

    def has_control(self):
        return True

    def stop_motors(self):
        pass

    def wheels(self, *args):
        pass

    def validate_result(self, response):
        pass

    def action(self, name, args):
        f = Future()
        f.set_result(None)
        return f

    def sensor_state(self):
        now = time.time()
        self.latest_image = SimpleNamespace(
            image_id=int(now * 10),
            image_recv_time=now,
            raw_image=PILImage.new("RGB", (32, 24), (20, 150, 160)),
        )
        return dict(
            received=now,
            cliff={"any_detected": False},
            picked_up=False,
            falling=False,
            proximity=dict(
                found_object=False, unobstructed=True, lift_in_fov=False, distance_mm=500
            ),
            pose=dict(x=0.1, y=0.2, yaw=0, origin_id=4),
            power=None,
            faces=[],
        )


class FixtureVectorConnection(VectorConnection):
    def __init__(self, **kwargs):
        Module.__init__(self, **kwargs)
        self.profile = profile("assistant", kind="vector")
        self.driver = FixtureDriver()
        self.controller = VectorController(self.driver, self.profile)
        self.done = threading.Event()
        self.count = 0
        self.last_image = None
        self.camera = None
        self.camera_received = 0
