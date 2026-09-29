import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from go2_setup.profiles import profile, module_plan
from go2_setup.robots import Robots
from go2_setup.api import create_app
from go2_setup.config import Settings

HEADERS = {"X-Go2-Request": "1"}


def test_dependencies_unknown_modules_and_preview_fail_closed():
    for selected in [
        ["navigation"],
        ["mapping"],
        ["exploration", "navigation"],
        ["voice"],
        ["shell"],
    ]:
        with pytest.raises(ValueError):
            profile("drive", selected)
    with pytest.raises(ValueError):
        profile("preview", ["teleop"])
    with pytest.raises(ValueError):
        profile("arbitrary-python-module")


def test_presets_compile_to_real_module_graphs_without_starting_hardware():
    from go2_setup.runtime import build_blueprint

    for name in ["preview", "drive", "map-record", "assistant"]:
        config = profile(name)
        blueprint = build_blueprint(config, replay="fixture.db")
        modules = {b.module.__name__ for b in blueprint.blueprints}
        assert {"PassiveGo2Connection", "ControlGate", "ConsoleBridge", "ConsoleSDK"} <= modules
        assert any(
            "RelayBridgeModule" in {c.__name__ for c in b.module.__mro__}
            for b in blueprint.blueprints
        )
        assert ("VoxelGridMapper" in modules) == (name in {"map-record", "assistant"})
        assert ("ReplanningAStarPlanner" in modules) == (name == "assistant")
        assert ("ConsoleExplorer" in modules) == (name == "assistant")
        assert len(modules) == len(module_plan(config))
    manual_map = profile("map-record", ["teleop", "lidar", "mapping", "recording"])
    modules = {b.module.__name__ for b in build_blueprint(manual_map).blueprints}
    assert "VoxelGridMapper" in modules
    assert not {"ReplanningAStarPlanner", "ConsoleExplorer"} & modules


def test_robot_migration_persistence_and_duplicate_rejection(tmp_path):
    robots = Robots(tmp_path, "192.168.1.73", "GO2-TEST")
    robot = robots.list()[0]
    assert robot["profile"] == profile()
    robots.remember_profile(robot["id"], profile("drive"))
    robots.save("Office Go2", "192.168.1.74", "GO2-TEST", ident=robot["id"])
    assert Robots(tmp_path).get(robot["id"])["profile"] == profile("drive")
    with pytest.raises(ValueError, match="already saved"):
        robots.save("Duplicate", "192.168.1.74")
    for ip in ["127.0.0.1", "0.0.0.0", "8.8.8.8", "224.0.0.1"]:
        with pytest.raises(ValueError):
            robots.save("Bad", ip)
    with pytest.raises(ValueError, match="Vector serial is required"):
        robots.save("Vector", "192.168.1.75", kind="vector")


def test_robot_connection_is_preview_and_cannot_start_motion(tmp_path, monkeypatch):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    s = app.state.supervisor
    monkeypatch.setattr(s, "_launch", lambda: None)
    with TestClient(app) as client:
        response = client.post(
            "/api/robots", headers=HEADERS, json={"name": "Desk", "ip": "192.168.1.73"}
        )
        ident = response.json()["id"]
        assert (
            client.post("/api/connect", headers=HEADERS, json={"robot_id": ident}).status_code
            == 200
        )
        assert s.profile == profile("preview") and s.mode == "idle"
        assert client.get("/api/state").json()["robot_id"] == ident
        s.connection = "online"
        s.call = Mock(return_value={})
        for mode in ["teleop", "explore", "agent"]:
            assert client.post("/api/mode", headers=HEADERS, json={"mode": mode}).status_code == 409
        s.call.assert_not_called()
        s.connection = "offline"


def test_apply_requires_idle_saved_recording_and_matching_robot(tmp_path, monkeypatch):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    s = app.state.supervisor
    monkeypatch.setattr(s, "_launch", lambda: None)
    with TestClient(app) as client:
        saved = s.robots.save("Go2", "192.168.1.73")
        s.connect(robot_id=saved["id"], config=profile("preview"))
        s.connection = "online"
        s.call = Mock(return_value={})
        body = {**profile("drive"), "robot_id": saved["id"]}
        s.mode = "teleop"
        assert client.post("/api/session/profile", headers=HEADERS, json=body).status_code == 409
        s.mode = "idle"
        s.session = {"id": "recording"}
        assert client.post("/api/session/profile", headers=HEADERS, json=body).status_code == 409
        s.session = None
        assert (
            client.post(
                "/api/session/profile", headers=HEADERS, json={**body, "robot_id": "other"}
            ).status_code
            == 409
        )
        s.call.assert_not_called()
        response = client.post("/api/session/profile", headers=HEADERS, json=body)
        assert response.status_code == 200, response.text
        s.call.assert_called_once_with("/halt")
        assert s.mode == "idle" and s.profile == profile("drive")
        assert s.robots.get(saved["id"])["profile"] == profile("drive")


def test_teleop_and_chat_do_not_require_mapping_but_navigation_does(monkeypatch):
    from go2_setup.modules import ControlGate
    from dimos.msgs.geometry_msgs.Twist import Twist

    monkeypatch.setattr("go2_setup.modules.Module.__init__", lambda self, **kwargs: None)
    monkeypatch.setenv(
        "GO2_SESSION_PROFILE", json.dumps(profile("assistant", ["teleop", "humancli"]))
    )
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = time.monotonic()
    epoch = gate.switch("teleop")
    assert gate.teleop(epoch, 0.1, 0, 0)
    epoch = gate.switch("agent")
    assert gate.heartbeat(epoch)
    assert not gate.navigation_enabled
    gate._nav(Twist((0.1, 0, 0)))
    assert gate.nav_forwarded == 0
    with pytest.raises(ValueError, match="disabled"):
        gate.navigation(epoch, True)
    with pytest.raises(ValueError, match="disabled"):
        gate.switch("explore")
    gate.profile = profile("assistant")
    with pytest.raises(ValueError, match="recent"):
        gate.navigation(epoch, True)
    gate.last_lidar = gate.last_map = time.monotonic()
    assert gate.navigation(epoch, True)
    gate._nav(Twist((0.1, 0, 0)))
    assert gate.nav_forwarded == 1
    gate.last_lidar = 0
    gate._nav(Twist((0.1, 0, 0)))
    assert gate.nav_forwarded == 1


def test_tools_follow_profile_and_cannot_be_invoked_when_disabled(tmp_path):
    from go2_setup.agent_tools import definitions, execute
    from test_humancli import agent_at, turn_for

    config = profile("assistant", ["camera", "humancli"])
    tools = {x["name"] for x in definitions(True, config)}
    assert {"camera_view", "robot_status"} <= tools
    assert not {"move_relative", "start_exploration", "start_recording"} & tools
    a = agent_at(tmp_path)
    a.supervisor.profile = config
    with pytest.raises(ValueError, match="disabled"):
        execute(a, turn_for(a), "start_exploration", {})
    a.supervisor.call.assert_not_called()


def test_disabled_recording_is_rejected_before_allocating_files(tmp_path):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    with TestClient(app):
        s = app.state.supervisor
        s.profile = profile("drive")
        with pytest.raises(ValueError, match="disabled"):
            s.start_recording("anything")
        assert s.session is None and s.segment is None


def test_go2_offers_two_presets_and_preserves_old_drive_choices():
    from go2_setup.profiles import PRESETS

    assert [p["name"] for p in PRESETS] == ["Teleop + Recording", "Full mode agent"]
    assert set(profile("map-record")["enabled"]) == {
        "teleop", "camera", "lidar", "mapping", "recording"
    }
    assert set(profile("assistant")["enabled"]) == {
        "teleop", "camera", "lidar", "mapping", "navigation", "exploration",
        "recording", "humancli", "voice"
    }
    assert profile("drive") == {"preset": "map-record", "enabled": ["teleop", "camera"]}
    assert profile("drive", ["teleop"])["enabled"] == ["teleop"]
