import math
import time
from unittest.mock import Mock

import pytest
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.robot.unitree.connection import UnitreeWebRTCConnection
from go2_setup.modules import ControlGate, PassiveGo2Connection
from go2_setup.agent import local_goal
from go2_setup.motion_transport import install_velocity_transport


@pytest.mark.parametrize(
    "phrase", ["camina 1 metro hacia atras", "andá un metro atrás", "caminá un metro hacia atrás"]
)
def test_spoken_backward_distance_respects_robot_heading(phrase):
    grid = dict(width=100, height=100, resolution=0.1, origin=[-5, -5], cells=[0] * 10000)
    x, y = local_goal(phrase, dict(x=0, y=0, yaw=math.pi / 2), grid)
    assert x == pytest.approx(0)
    assert y == pytest.approx(-1)


def test_nav_and_strafe_pass_the_gate_but_expired_commands_do_not(monkeypatch):
    monkeypatch.setattr("go2_setup.modules.Module.__init__", lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = time.monotonic()
    token = gate.switch("teleop")
    assert gate.teleop(token, 0, 0.2, 0)
    assert gate.cmd_vel.publish.call_args.args[0].linear.y == 0.2
    gate.switch("explore")
    assert not gate.teleop(token, 0, 0.2, 0)
    gate._nav(Twist((0.1, -0.2, 0), (0, 0, 0.3)))
    assert gate.nav_received == gate.nav_forwarded == 1
    assert gate.cmd_vel.publish.call_args.args[0].angular.z == 0.3
    gate.halt()
    gate._nav(Twist((1, 1, 0), (0, 0, 1)))
    assert gate.nav_received == 2
    assert gate.nav_forwarded == 1
    assert not gate.cmd_vel.publish.call_args.args[0]


def test_metric_velocity_uses_mcf_noreply_envelope_and_preserves_axes():
    import json
    from unitree_webrtc_connect.msgs.pub_sub import WebRTCDataChannelPubSub

    wire = object.__new__(UnitreeWebRTCConnection)
    wire._velocity_api = True
    wire.conn = Mock()
    channel = Mock(readyState="open")
    wire.conn.datachannel.pub_sub = WebRTCDataChannelPubSub(channel)
    wire._move_ids = Mock()
    wire._move_ids.next.return_value = 1
    assert install_velocity_transport(wire)
    wire._publish_movement(0, -0.2, 0.3)
    frame = json.loads(channel.send.call_args.args[0])
    assert frame["topic"] == "rt/api/sport/request"
    assert frame["type"] == "msg"
    assert frame["data"]["header"]["identity"]["api_id"] == 1008
    assert frame["data"]["header"]["policy"] == {"priority": 0, "noreply": True}
    assert frame["data"]["binary"] == []
    assert json.loads(frame["data"]["parameter"]) == {"x": 0, "y": -0.2, "z": 0.3}
    assert "lx" not in frame["data"]


def test_mcf_adapter_excludes_replay_and_joystick():
    from dimos.robot.unitree.go2.connection import ReplayConnection

    assert not install_velocity_transport(object.__new__(ReplayConnection))
    wire = object.__new__(UnitreeWebRTCConnection)
    wire._velocity_api = False
    assert not install_velocity_transport(wire)


def test_mcf_closed_channel_is_reported_as_error():
    wire = object.__new__(UnitreeWebRTCConnection)
    wire._velocity_api = True
    wire.conn = Mock()
    wire.conn.datachannel.pub_sub.channel.readyState = "closed"
    assert install_velocity_transport(wire)
    with pytest.raises(ConnectionError, match="closed"):
        wire._publish_movement(0.1, 0, 0)
    wire.conn.datachannel.pub_sub.publish_without_callback.assert_not_called()


def test_mcf_watchdog_sends_zero_using_same_envelope():
    import asyncio
    import json
    import threading

    wire = object.__new__(UnitreeWebRTCConnection)
    wire._velocity_api = True
    wire.conn = Mock()
    wire.conn.datachannel.pub_sub.channel.readyState = "open"
    wire._move_ids = Mock()
    wire._move_ids.next.return_value = 1
    wire.stop_timer = None
    wire.cmd_vel_timeout = 0.05
    wire.loop = asyncio.new_event_loop()
    ready, stopped = threading.Event(), threading.Event()
    frames = []

    def send(*args, **kwargs):
        frames.append(kwargs)
        if json.loads(kwargs["data"]["parameter"]) == {"x": 0, "y": 0, "z": 0}:
            stopped.set()

    wire.conn.datachannel.pub_sub.publish_without_callback.side_effect = send
    wire.loop.call_soon(ready.set)
    thread = threading.Thread(target=wire.loop.run_forever)
    thread.start()
    assert ready.wait(1)
    try:
        assert install_velocity_transport(wire)
        assert wire.move(Twist((0, 0.2, 0)))
        assert stopped.wait(2), "Automatic stop did not send a zero command"
        assert len(frames) == 2
        assert all(frame["msg_type"] == "msg" for frame in frames)
        assert json.loads(frames[0]["data"]["parameter"])["y"] == 0.2
    finally:
        if wire.stop_timer:
            wire.stop_timer.cancel()
        wire.loop.call_soon_threadsafe(wire.loop.stop)
        thread.join(2)
        wire.loop.close()


def test_connection_reports_failed_motion_instead_of_claiming_sent():
    connection = object.__new__(PassiveGo2Connection)
    connection._motion = dict(count=0, sent=0, errors=0, last=None, error=None)
    connection.move = Mock(return_value=False)
    connection._receive_velocity(Twist((0, 0.2, 0)))
    assert connection._motion["sent"] == 0
    assert connection._motion["errors"] == 1
    connection.move.return_value = True
    connection._receive_velocity(Twist((0, -0.2, 0)))
    assert connection._motion["sent"] == 1
    assert connection._motion["error"] is None


def test_exploration_stop_wakes_old_thread_without_publishing_a_new_goal():
    import threading
    from go2_setup.modules import ConsoleExplorer

    explorer = object.__new__(ConsoleExplorer)
    explorer.exploration_active = True
    explorer.no_gain_counter = 2
    explorer.stop_event = threading.Event()
    explorer.goal_reached_event = threading.Event()
    explorer.goal_request = Mock()
    explorer.exploration_thread = threading.Thread(
        target=lambda: explorer.goal_reached_event.wait(30)
    )
    explorer.exploration_thread.start()
    assert explorer.stop_exploration()
    assert not explorer.exploration_thread.is_alive()
    assert explorer.stop_event.is_set()
    explorer.goal_request.publish.assert_not_called()


@pytest.mark.parametrize("speed", [0.5, -0.5, 0.55, 1.0])
def test_forward_speed_is_not_clipped_in_teleop_or_navigation(monkeypatch, speed):
    monkeypatch.setattr("go2_setup.modules.Module.__init__", lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = time.monotonic()
    epoch = gate.switch("teleop")
    assert gate.teleop(epoch, speed, 0, 0)
    assert gate.cmd_vel.publish.call_args.args[0].linear.x == speed
    gate.switch("explore")
    gate._nav(Twist((speed, 0, 0)))
    assert gate.cmd_vel.publish.call_args.args[0].linear.x == speed
