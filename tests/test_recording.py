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


def test_command_streams_roundtrip_and_keep_enqueue_timestamps(tmp_path, monkeypatch):
    import sqlite3
    from dimos.msgs.geometry_msgs.Twist import Twist

    now = [1000.1]
    monkeypatch.setattr('go2_setup.modules.time.time', lambda: now[0])
    writer = SessionWriter(tmp_path / 'commands.db')
    pose = PoseStamped(position=[1, 2, 0], frame_id='world', ts=1000.0)
    writer.enqueue('teleop_requested', Twist((0.5, 0.6, 0), (0, 0, 0.8)), pose)
    now[0] = 1000.2
    writer.enqueue('cmd_vel', Twist((0.5, 0.2, 0), (0, 0, 0.5)), pose)
    now[0] = 1000.3
    writer.enqueue('cmd_vel', Twist(), pose)
    now[0] = 2000.0  # Disk processing time must not replace reception time.
    writer.close()
    assert writer.state()['error'] is None
    assert writer.counts == {'teleop_requested': 1, 'cmd_vel': 2}
    with sqlite3.connect(writer.path) as db:
        assert db.execute('SELECT ts FROM teleop_requested').fetchall() == [(1000.1,)]
        assert db.execute('SELECT ts FROM cmd_vel ORDER BY ts').fetchall() == [(1000.2,), (1000.3,)]
    stats = inspect_recording(writer.path)
    assert stats['streams']['cmd_vel']['poses'] == 2
    store = SqliteStore(path=str(writer.path), must_exist=True)
    store.start()
    try:
        requested = store.stream('teleop_requested').first()
        output = store.stream('cmd_vel').first()
        assert requested.data.linear.y == 0.6
        assert output.data.linear.y == 0.2
        assert output.data.angular.z == 0.5
        assert output.tags['reception_ts'] == 1000.2
        assert not store.stream('cmd_vel').last().data
    finally:
        store.stop()


def test_gate_to_recorder_preserves_requested_bounded_rejected_and_stop_commands(tmp_path, monkeypatch):
    import threading
    import time
    from unittest.mock import Mock
    from go2_setup.modules import ControlGate, ConsoleBridge

    monkeypatch.setattr('go2_setup.modules.Module.__init__', lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = time.monotonic()
    epoch = gate.switch('teleop')
    bridge = object.__new__(ConsoleBridge)
    bridge.lock = threading.RLock()
    bridge.telemetry = {'sensors': {}}
    bridge.latest_pose = PoseStamped(position=[1, 2, 0], frame_id='world')
    bridge.writer = SessionWriter(tmp_path / 'gate.db')
    gate.teleop_requested.publish.side_effect = lambda msg: bridge._sensor('teleop_requested', msg)
    gate.cmd_vel.publish.side_effect = lambda msg: bridge._sensor('cmd_vel', msg)
    assert gate.teleop(epoch, 0.5, 0.6, 0.8)
    gate.halt()
    assert not gate.teleop(epoch, 0.5, 0.6, 0.8)
    bridge.writer.close()
    assert bridge.writer.state()['error'] is None
    assert bridge.writer.counts == {'teleop_requested': 2, 'cmd_vel': 2}
    assert not gate.cmd_vel.publish.call_args.args[0]
    store = SqliteStore(path=str(bridge.writer.path), must_exist=True)
    store.start()
    try:
        assert store.stream('teleop_requested').first().data.linear.y == 0.6
        assert store.stream('cmd_vel').first().data.linear.y == 0.2
    finally:
        store.stop()
