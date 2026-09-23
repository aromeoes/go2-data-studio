import numpy as np
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Transform import Transform
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.CameraInfo import CameraInfo
from dimos.msgs.tf2_msgs.TFMessage import TFMessage
from dimos.memory.store.sqlite import SqliteStore

from go2_setup.modules import SessionWriter
from go2_setup.records import inspect_recording


def test_all_five_streams_roundtrip_with_pose_and_original_clock(tmp_path):
    path = tmp_path / "raw.db"
    writer = SessionWriter(path)
    for i in range(3):
        ts = 1000.0 + i * 0.2
        pose = PoseStamped(position=[i, 0, 0], frame_id="world", ts=ts)
        cloud = PointCloud2.from_numpy(
            np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float32),
            frame_id="world",
            timestamp=ts,
        )
        image = Image.from_numpy(np.zeros((32, 32, 3), dtype=np.uint8), ts=ts)
        writer.enqueue("odom", pose, pose)
        writer.enqueue("lidar", cloud, pose)
        writer.enqueue("color_image", image, pose)
        writer.enqueue(
            "tf", TFMessage(Transform(frame_id="world", child_frame_id="base_link", ts=ts)), None
        )
        writer.enqueue("camera_info", CameraInfo(ts=ts), None)
    writer.close()
    assert writer.state()["error"] is None
    stats = inspect_recording(path)
    assert stats["duration"] < 1
    assert stats["streams"]["lidar"]["poses"] == 3
    assert stats["streams"]["color_image"]["count"] == 3
    assert stats["streams"]["tf"]["count"] == 3
    store = SqliteStore(path=str(path), must_exist=True)
    store.start()
    try:
        assert store.stream("lidar").first().data.frame_id == "world"
        assert store.stream("color_image").first().data.to_opencv().shape == (32, 32, 3)
    finally:
        store.stop()
