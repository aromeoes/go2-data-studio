from unittest.mock import Mock

from go2_setup.catalog import Catalog
from go2_setup.config import Settings
from go2_setup.supervisor import Supervisor


def test_robot_loss_keeps_session_but_opens_new_coordinate_segment(tmp_path):
    cfg = Settings(root=tmp_path, env_file=tmp_path / "missing")
    cfg.initialize()
    catalog = Catalog(tmp_path)
    space = catalog.space("Prueba")
    supervisor = Supervisor(cfg, catalog)
    supervisor.done.set()
    supervisor.target = {"ip": "192.168.1.20", "replay": None}
    supervisor.connection = "online"
    supervisor.call = Mock(return_value={})
    session = supervisor.start_recording(space["id"])
    old_segment = supervisor.segment
    supervisor._lost("Robot apagado")
    assert supervisor.session["id"] == session["id"]
    assert supervisor.segment is None
    assert supervisor.mode == "idle"
    assert supervisor.connection == "reconnecting"
    assert catalog.get(old_segment["id"])["status"] == "interrupted"
    supervisor.connection = "online"
    supervisor._begin_segment()
    assert supervisor.segment["id"] != old_segment["id"]
    assert supervisor.segment["frame_epoch"] != old_segment["frame_epoch"]
    supervisor.target = None
    supervisor._end_segment(interrupted=True)
    supervisor.session = None


def test_delayed_state_does_not_restore_an_old_control_lease(tmp_path):
    cfg = Settings(root=tmp_path, env_file=tmp_path / "missing")
    cfg.initialize()
    supervisor = Supervisor(cfg, Catalog(tmp_path))
    supervisor.done.set()
    supervisor.mode, supervisor.epoch = "teleop", 8
    supervisor.accept_telemetry({"control": {"mode": "explore", "epoch": 6}})
    assert supervisor.mode == "teleop"
    assert supervisor.epoch == 8
    assert supervisor.telemetry["control"]["epoch"] == 8
    supervisor.accept_telemetry({"control": {"mode": "idle", "epoch": 9}})
    assert supervisor.mode == "idle"


def test_remembered_ip_overrides_old_environment_without_connecting(tmp_path):
    env_file = tmp_path / "robot.env"
    env_file.write_text("ROBOT_IP=192.168.50.9\n")
    cfg = Settings(root=tmp_path, env_file=env_file)
    cfg.initialize()
    first = Supervisor(cfg, Catalog(tmp_path))
    first.done.set()
    first.ip = "192.168.50.42"
    first.target = {"ip": first.ip, "replay": None}
    first.remember_ip()
    second = Supervisor(cfg, Catalog(tmp_path))
    second.done.set()
    assert second.ip == "192.168.50.42"
    assert second.target is None
    assert second.connection == "offline"
    assert second.process is None
    assert second.mode == "idle"


def test_corrupt_or_other_robot_saved_ip_is_ignored(tmp_path):
    import json

    cfg = Settings(root=tmp_path, env_file=tmp_path / "missing")
    cfg.initialize()
    for contents in (
        "broken",
        json.dumps({"ip": "192.168.50.42", "serial": "another"}),
        json.dumps({"ip": "127.0.0.1", "serial": cfg.serial}),
    ):
        (tmp_path / "connection.json").write_text(contents)
        supervisor = Supervisor(cfg, Catalog(tmp_path))
        supervisor.done.set()
        assert supervisor.ip == ""
        assert supervisor.target is None
