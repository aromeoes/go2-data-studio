import time
from unittest.mock import Mock

import pytest

from dimos.msgs.geometry_msgs.Twist import Twist
from go2_setup.control import Authority, go2_sensor_recent
from go2_setup.modules import ControlGate


@pytest.mark.parametrize('age,allowed', [(1.1, True), (5.1, True), (9.99, True), (10, True), (10.01, False)])
@pytest.mark.parametrize('mode', ['teleop', 'explore', 'agent'])
def test_commands_and_watchdog_share_ten_second_grace(monkeypatch, age, allowed, mode):
    monkeypatch.setattr('go2_setup.modules.Module.__init__', lambda self, **kwargs: None)
    monkeypatch.setattr('go2_setup.modules.time.monotonic', lambda: 100.0)
    gate = ControlGate()
    gate.authority = Authority(clock=lambda: 100.0)
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = 100.0 - age
    epoch = gate.switch(mode)
    gate.cmd_vel.reset_mock()
    if mode == 'teleop':
        assert gate.teleop(epoch, 0.1, 0, 0) is allowed
    else:
        if mode == 'agent':
            if allowed:
                assert gate.navigation(epoch, True)
            else:
                with pytest.raises(ValueError, match='recent'):
                    gate.navigation(epoch, True)
                gate.navigation_enabled = True
        gate._nav(Twist((0.1, 0, 0)))
        assert gate.nav_forwarded == int(allowed)
    gate.done = Mock()
    gate.done.wait.side_effect = [False, True]
    gate._watchdog()
    assert gate.authority.mode == (mode if allowed else 'idle')
    if not allowed:
        assert not gate.cmd_vel.publish.call_args.args[0]
        assert '10 seconds' in gate.stop_reason


@pytest.mark.parametrize('field', ['last_odom', 'last_lidar', 'last_map'])
def test_each_required_navigation_stream_expires_independently(monkeypatch, field):
    monkeypatch.setattr('go2_setup.modules.Module.__init__', lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = time.monotonic()
    setattr(gate, field, time.monotonic() - 10.1)
    gate.switch('explore')
    gate._nav(Twist((0.1, 0, 0)))
    assert gate.nav_forwarded == 0
    gate.done = Mock()
    gate.done.wait.side_effect = [False, True]
    gate._watchdog()
    assert gate.authority.mode == 'idle'


def test_initial_data_required_and_controller_expiry_not_extended(monkeypatch):
    assert not go2_sensor_recent(0, 1)
    assert go2_sensor_recent(90, 100)
    assert not go2_sensor_recent(89.9, 100)
    monkeypatch.setattr('go2_setup.modules.Module.__init__', lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = time.monotonic()
    gate.switch('teleop')
    gate.authority.deadline = 0
    gate.done = Mock()
    gate.done.wait.side_effect = [False, True]
    gate._watchdog()
    assert gate.authority.mode == 'idle'
    assert gate.stop_reason == 'Page control lease expired'


@pytest.mark.parametrize('kind,age,lost', [('go2', 5.1, False), ('go2', 10, False), ('go2', 10.01, True), ('vector', 5.1, True)])
def test_supervisor_does_not_reconnect_go2_before_grace(monkeypatch, kind, age, lost):
    import threading
    from go2_setup.supervisor import Supervisor

    monkeypatch.setattr('go2_setup.supervisor.time.time', lambda: 100.0)
    monkeypatch.setattr('go2_setup.supervisor.time.monotonic', lambda: 100.0)
    supervisor = object.__new__(Supervisor)
    supervisor.lock = threading.RLock()
    supervisor.done = Mock()
    supervisor.done.wait.side_effect = [False, True]
    supervisor.target = {'kind': kind, 'replay': None}
    supervisor.process = Mock()
    supervisor.process.poll.return_value = None
    supervisor.connection = 'online'
    supervisor.error = None
    supervisor.started = 0
    supervisor.segment = supervisor.session = None
    supervisor.telemetry = {'sensors': {'odom': {'received': 100.0 - age}}}
    supervisor.call = Mock(return_value=supervisor.telemetry)
    supervisor.accept_telemetry = Mock()
    supervisor.diagnostics = Mock()
    supervisor._lost = Mock()
    supervisor._monitor()
    assert supervisor.error is None
    assert supervisor._lost.called is lost
