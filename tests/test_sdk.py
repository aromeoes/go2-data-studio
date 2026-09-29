import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from go2_setup.api import create_app
from go2_setup.catalog import Catalog
from go2_setup.config import Settings
from go2_setup.supervisor import Supervisor


def test_replay_only_cannot_connect_or_launch_physical_robot(tmp_path):
    cfg = Settings(root=tmp_path, env_file=tmp_path / "none", replay_only=True)
    s = Supervisor(cfg, Catalog(tmp_path))
    try:
        with pytest.raises(ValueError, match="physical robot connections are disabled"):
            s.connect("192.168.50.42")
        s.target = {"ip": "192.168.50.42", "replay": None}
        with pytest.raises(ValueError, match="physical robot connections are disabled"):
            s._launch()
        s.target = None
    finally:
        s.close()


def test_sdk_commands_require_bridge_auth_and_reject_expired_commands(tmp_path):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "none"))
    s = app.state.supervisor
    s.change_mode = Mock(return_value={"epoch": 7, "mode": "agent"})
    item = {
        "id": "test",
        "client": "test-console",
        "path": "/mode",
        "body": {"mode": "agent"},
        "sent": time.time(),
    }
    headers = {"X-Go2-Request": "1"}
    with TestClient(app) as client:
        assert client.post("/api/sdk/command", json=item, headers=headers).status_code == 403
        headers["Authorization"] = "Bearer " + s.token
        item["sent"] -= 20
        assert client.post("/api/sdk/command", json=item, headers=headers).status_code == 409
        s.change_mode.assert_not_called()
        item["sent"] = time.time()
        assert client.post("/api/sdk/command", json=item, headers=headers).json()["epoch"] == 7
        item["path"] = "/connect"
        assert client.post("/api/sdk/command", json=item, headers=headers).status_code == 409
        assert client.get("/api/sdk/state").status_code == 403


def test_manifest_has_native_channels_without_cockpit_layout():
    from go2_setup.sdk_bridge import sdk_blueprint

    manifest = sdk_blueprint().blueprints[0].kwargs["manifest"]
    assert manifest["layout"] is None
    assert not manifest["panels"]
    channels = {ch["ch"]: ch for ch in manifest["channels"]}
    assert channels["tele_cmd_vel"]["publish"] == "none"
    assert channels["tele_cmd_vel"]["params"]["watchdogMs"] == 300
    assert channels["console_command"]["publish"] == "shared"
    assert channels["color_image"]["encoding"] == "jpeg.v1"


def test_sdk_owner_blocks_other_viewers_and_commands_queued_before_stop():
    from go2_setup.sdk_control import CommandOwner

    now = [10.0]
    owner = CommandOwner(clock=lambda: now[0])

    def command(client, path, sent=100):
        owner.authorize({"client": client, "path": path, "sent": sent})

    command("one", "/mode")
    with pytest.raises(ValueError, match="Another console"):
        command("two", "/mode")
    command("two", "/stop", 101)
    with pytest.raises(ValueError, match="cancelled by Stop"):
        command("one", "/mode", 100.5)
    command("two", "/mode", 102)
    now[0] += 3
    with pytest.raises(ValueError, match="expired"):
        command("two", "/heartbeat", 103)
    command("one", "/mode", 104)


def test_sdk_twists_obey_mode_stop_latch_and_position_freshness():
    from go2_setup.control import Authority
    from go2_setup.modules import ControlGate
    from dimos.msgs.geometry_msgs.Twist import Twist

    gate = object.__new__(ControlGate)
    from go2_setup.profiles import profile

    gate.profile = profile("legacy")
    gate.authority = Authority()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = time.monotonic()
    gate.last_teleop = 0
    gate._sdk_teleop(Twist((0.5, 0, 0)))
    gate.cmd_vel.publish.assert_not_called()
    gate.authority.transition("teleop")
    gate._sdk_teleop(Twist((0.5, 0.5, 0), (0, 0, 0.5)))
    value = gate.cmd_vel.publish.call_args.args[0]
    assert value.linear.x == 0.5
    assert value.linear.y == 0.2  # Existing lateral hardware bound remains.
    gate.authority.halt(True)
    gate.cmd_vel.publish.reset_mock()
    gate._sdk_teleop(Twist((0.5, 0, 0)))
    gate.cmd_vel.publish.assert_not_called()
    gate.authority.clear()
    gate.authority.transition("teleop")
    gate.last_odom -= 11
    gate._sdk_teleop(Twist((0.5, 0, 0)))
    gate.cmd_vel.publish.assert_not_called()


def test_sdk_stop_has_an_independent_queue_and_commands_are_not_retried():
    import json
    import queue
    import threading
    from go2_setup.sdk_bridge import ConsoleSDK

    bridge = object.__new__(ConsoleSDK)
    bridge.lock = threading.Lock()
    bridge.seen = set()
    bridge.results = {}
    bridge.commands = queue.Queue(maxsize=1)
    bridge.urgent = queue.Queue(maxsize=1)
    raw = json.dumps({"id": "one", "path": "/posture/stand"})
    bridge._command(raw)
    bridge._command(raw)
    assert bridge.commands.qsize() == 1
    bridge._command(json.dumps({"id": "stop", "path": "/stop"}))
    assert bridge.urgent.get_nowait()["path"] == "/stop"
    bridge._command(json.dumps({"id": "overflow", "path": "/mode"}))
    assert "busy" in bridge.results["overflow"]["error"]


def test_vector_teleop_manifest_matches_differential_drive_limits():
    from go2_setup.vector.runtime import build_blueprint
    from go2_setup.profiles import profile

    bp = build_blueprint(profile('drive', kind='vector'))
    manifests = [b.kwargs['manifest'] for b in bp.blueprints if 'manifest' in b.kwargs]
    assert len(manifests) == 1
    teleop = next(ch for ch in manifests[0]['channels'] if ch['ch'] == 'tele_cmd_vel')
    assert teleop['params']['maxLinear'] == 0.12
    assert teleop['params']['maxAngular'] == 1.5
    assert teleop['params']['watchdogMs'] == 300
