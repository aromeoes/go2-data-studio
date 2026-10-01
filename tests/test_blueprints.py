from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from go2_setup.agent_tools import tool_enabled
from go2_setup.api import create_app
from go2_setup.blueprints import base_profile, catalog, has_module, session_profile
from go2_setup.config import Settings
from go2_setup.profiles import module_plan, profile
from go2_setup.runtime import added_modules, extra_modules

HEADERS = {"X-Go2-Request": "1"}


def teleop_modules(kind="go2"):
    return next(b for b in catalog(kind)["blueprints"] if b["id"] == "teleop")["modules"]


def test_base_connection_loads_only_required_modules():
    base = base_profile("go2")
    assert base["modules"] == ["GO2Connection", "ControlGate", "RelayBridgeModule"]
    assert set(base["enabled"]) == {"camera", "lidar", "teleop"}
    assert extra_modules(base) == []
    assert base_profile("vector")["modules"] == ["VectorConnection", "RelayBridgeModule", "VectorTelemetry"]


def test_module_rules():
    teleop = session_profile("go2", "teleop", teleop_modules())
    assert "humancli" not in teleop["enabled"] and "recording" in teleop["enabled"]
    with pytest.raises(ValueError, match="cannot be changed"):
        session_profile("go2", "teleop", [*teleop_modules(), "McpClient"])
    with pytest.raises(ValueError, match="requires"):
        session_profile("go2", "custom", [*teleop_modules(), "WavefrontFrontierExplorer"])
    with pytest.raises(ValueError, match="Required"):
        session_profile("go2", "custom", ["ControlGate", "RelayBridgeModule"])
    with pytest.raises(ValueError, match="not available"):
        session_profile("vector", "custom", [*teleop_modules("vector"), "VoxelGridMapper"])
    explore = session_profile(
        "go2", "custom", [*teleop_modules(), "ReplanningAStarPlanner", "McpClient", "WavefrontFrontierExplorer"]
    )
    assert {"navigation", "exploration", "humancli"} <= set(explore["enabled"])
    assert module_plan(explore) == explore["modules"]
    assert profile(**explore) == explore


def test_runtime_adds_modules_in_start_order_and_never_removes():
    base = base_profile("go2")
    full = session_profile(
        "go2", "custom", [*teleop_modules(), "ReplanningAStarPlanner", "McpClient", "WavefrontFrontierExplorer"]
    )
    assert added_modules(base, full) == ["VoxelGridMapper", "CostMapper", "ReplanningAStarPlanner", "WavefrontFrontierExplorer"]
    assert added_modules(full, full) == []
    with pytest.raises(ValueError, match="cannot be removed"):
        added_modules(full, base)


def test_humancli_tools_follow_selected_modules():
    chat_only = session_profile("go2", "custom", [*teleop_modules(), "McpClient"])
    assert not tool_enabled("start_patrol", chat_only)
    assert not tool_enabled("navigate_with_text", chat_only)
    with_places = session_profile(
        "go2", "custom", [*teleop_modules(), "ReplanningAStarPlanner", "McpClient", "NavigationSkillContainer"]
    )
    assert tool_enabled("navigate_with_text", with_places) and not tool_enabled("speak", with_places)
    # Profiles saved before blueprints keep every tool their capabilities allow.
    assert tool_enabled("speak", profile("assistant")) and has_module(profile("assistant"), "SpeakSkill")


def test_control_gate_hold_blocks_teleop_and_navigation():
    from go2_setup.control import Authority
    from go2_setup.modules import ControlGate

    gate = ControlGate.__new__(ControlGate)
    gate.authority, gate.profile = Authority(), profile("assistant")
    gate.cmd_vel, gate.teleop_requested = Mock(), Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = 1e12
    gate.navigation_enabled, gate.nav_received, gate.nav_forwarded = True, 0, 0
    epoch = gate.authority.transition("teleop")
    ControlGate.set_hold(gate, True)
    assert ControlGate.teleop(gate, epoch, 0.3, 0, 0) is False
    ControlGate.set_hold(gate, False)
    assert ControlGate.teleop(gate, epoch, 0.3, 0, 0) is True


def test_starting_space_hold_and_sign_out(tmp_path, monkeypatch):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    s, cloud = app.state.supervisor, app.state.cloud
    monkeypatch.setattr(s, "_launch", lambda: None)
    with TestClient(app) as client:
        state = client.get("/api/state").json()
        assert [x["name"] for x in state["spaces"]] == ["Starting space"]
        saved = s.robots.save("Go2", "192.168.1.73")
        assert client.post("/api/connect", headers=HEADERS, json={"robot_id": saved["id"]}).status_code == 200
        s.connection = "online"
        s.call = Mock(return_value={"ok": True})
        # Before START nothing moves, not even a posture change.
        assert client.post("/api/posture/stand", headers=HEADERS).status_code == 409
        assert client.post("/api/hold", headers=HEADERS, json={"on": True}).status_code == 200
        s.call.assert_called_with("/hold", {"on": True}, timeout=10)
        assert client.get("/api/state").json()["hold"] is True
        s.connection = "offline"
        cloud.credentials.write_text('{"api_key": "x"}')
        cloud.account = {"email": "a@b.c", "id": "1"}
        assert client.post("/api/cloud/signout", headers=HEADERS).status_code == 200
        assert not cloud.credentials.exists() and client.get("/api/state").json()["cloud"]["account"] is None
