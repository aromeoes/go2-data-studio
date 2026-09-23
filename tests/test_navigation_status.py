from go2_setup.navigation_status import NavigationStatus
from go2_setup.modules import PassiveGo2Connection


def telemetry(now=100, epoch=1, mode="explore", yaw=0, command=0.23):
    return dict(
        control=dict(mode=mode, epoch=epoch),
        pose=dict(x=0, y=0, yaw=yaw),
        sensors={"odom": {"received": now}},
        motion={"last": dict(x=0, y=0, yaw=command, received=now)},
    )


def append(path, text):
    with path.open("a") as stream:
        stream.write(text + "\n")


def test_new_runtime_ignores_old_messages_and_reads_split_lines(tmp_path):
    path = tmp_path / "runtime.log"
    path.write_text("[local_planner.py] Obstacle detected ahead, stopping local planner.\n")
    status = NavigationStatus(path, clock=lambda: 100)
    assert not status.snapshot(telemetry())["warnings"]
    with path.open("a") as stream:
        stream.write("[local_planner.py] changed state state=initial_")
    assert status.snapshot(telemetry())["phase"] == "waiting"
    append(path, "rotation")
    assert status.snapshot(telemetry())["phase"] == "initial_rotation"


def test_obstacle_warning_survives_immediate_replan_but_expires(tmp_path):
    now = [100]
    path = tmp_path / "runtime.log"
    status = NavigationStatus(path, clock=lambda: now[0])
    status.snapshot(telemetry())
    append(path, "[local_planner.py] Obstacle detected ahead, stopping local planner.")
    append(path, "[global_planner.py] Replanning. attempt=1")
    append(path, "[global_planner.py] Found path 1.1x robot width.")
    append(path, "[local_planner.py] changed state state=initial_rotation")
    result = status.snapshot(telemetry())
    assert result["phase"] == "initial_rotation"
    assert result["warnings"][0]["code"] == "obstacle"
    now[0] = 111
    assert not status.snapshot(telemetry(now=111, command=0))["warnings"]
    assert any(e["code"] == "obstacle" for e in status.events)


def test_no_observed_rotation_requires_continuous_fresh_commands(tmp_path):
    now = [100]
    status = NavigationStatus(None, clock=lambda: now[0])
    assert not status.snapshot(telemetry())["warnings"]
    now[0] = 103
    assert not status.snapshot(telemetry(now=103))["warnings"]
    now[0] = 104
    result = status.snapshot(telemetry(now=104))
    assert result["warnings"][0]["code"] == "no_observed_motion"
    assert result["warnings"][0]["source"] == "odometry"
    now[0] = 105
    assert not status.snapshot(telemetry(now=105, yaw=0.2))["warnings"]
    now[0] = 110
    assert not status.snapshot(telemetry(now=100, yaw=0.2))["warnings"]
    now[0] = 111
    assert not status.snapshot(telemetry(now=111, yaw=0.2))["warnings"]


def test_new_epoch_pause_and_no_command_reset_stall(tmp_path):
    now = [100]
    status = NavigationStatus(None, clock=lambda: now[0])
    status.snapshot(telemetry())
    now[0] = 105
    assert not status.snapshot(telemetry(now=105, epoch=2))["warnings"]
    now[0] = 110
    assert not status.snapshot(telemetry(now=110, mode="idle"))["warnings"]
    assert status.snapshot(telemetry(now=110, mode="idle"))["phase"] == "paused"
    assert not status.snapshot(telemetry(now=110, command=0))["warnings"]


def test_no_path_cleared_by_new_path_and_history_bounded(tmp_path):
    status = NavigationStatus(None, clock=lambda: 100)
    status.snapshot(telemetry())
    status.feed("[global_planner.py] No path found to the goal. x=2 y=3")
    assert status.snapshot(telemetry())["phase"] == "no_path"
    status.feed("[global_planner.py] Found path 1.1x robot width.")
    assert not status.snapshot(telemetry())["warnings"]
    for i in range(30):
        status.feed("[global_planner.py] Replanning. attempt=1")
        status.feed("[local_planner.py] changed state state=initial_rotation")
    assert len(status.events) == 8
    status.feed("[other_module.py] Obstacle detected ahead")
    assert not status.snapshot(telemetry())["warnings"]


def test_battery_zero_valid_invalid_sample_does_not_refresh(monkeypatch):
    monkeypatch.setattr("go2_setup.modules.time.time", lambda: 100)
    connection = object.__new__(PassiveGo2Connection)
    connection._battery = {"percent": None, "received": None}
    assert connection.battery_state()["percent"] is None
    connection._on_lowstate({"data": {"bms_state": {"soc": 0}}})
    assert connection.battery_state() == {"percent": 0, "received": 100}
    for invalid in [None, True, 101, -1, "bad", float("nan")]:
        connection._on_lowstate({"data": {"bms_state": {"soc": invalid}}})
        assert connection.battery_state() == {"percent": 0, "received": 100}
    connection._on_lowstate({"data": {"bms_state": {"soc": 72}}})
    assert connection.battery_state()["percent"] == 72
