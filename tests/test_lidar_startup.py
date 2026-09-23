import asyncio
import threading
from unittest.mock import Mock

import pytest
from dimos.robot.unitree.connection import UnitreeWebRTCConnection
from dimos.robot.unitree.go2.connection import ReplayConnection

from go2_setup.lidar_startup import _enable, enable_lidar


def test_lidar_startup_only_publishes_sensor_on_messages():
    wire = object.__new__(UnitreeWebRTCConnection)
    wire.conn = Mock()
    publisher = wire.conn.datachannel.pub_sub
    publisher.channel.readyState = "open"
    wire.loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(wire.loop)
        wire.loop.call_soon(ready.set)
        wire.loop.run_forever()

    thread = threading.Thread(target=run)
    thread.start()
    assert ready.wait(2)
    try:
        assert enable_lidar(wire)
        assert publisher.publish_without_callback.call_count == 5
        for call in publisher.publish_without_callback.call_args_list:
            assert call.args == ("rt/utlidar/switch", "ON")
        wire.conn.datachannel.pub_sub.publish_request_new.assert_not_called()
    finally:
        wire.loop.call_soon_threadsafe(wire.loop.stop)
        thread.join(timeout=2)
        wire.loop.close()


def test_lidar_startup_does_not_turn_replay_into_a_hardware_sender():
    assert enable_lidar(object.__new__(ReplayConnection)) is False


def test_closed_channel_reports_failure_instead_of_claiming_enabled():
    publisher = Mock()
    publisher.channel.readyState = "closed"
    with pytest.raises(ConnectionError, match="data channel is closed"):
        asyncio.run(_enable(publisher))
    publisher.publish_without_callback.assert_not_called()
