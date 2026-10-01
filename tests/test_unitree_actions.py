from unittest.mock import Mock
import pytest
from go2_setup.unitree_actions import catalog, execute, PARAMETERIZED


def run(connection, name="Hello", **kwargs):
    return execute(
        connection,
        name,
        control=kwargs.pop("control", {"mode": "idle", "epoch": 3, "estop": False}),
        epoch=3,
        confirmed=name,
        **kwargs,
    )


def test_registry_matches_pinned_dimos_and_parameterized_actions_are_explained():
    from dimos.robot.unitree.unitree_skill_container import UNITREE_WEBRTC_CONTROLS

    assert [(a["name"], a["api_id"]) for a in catalog()] == [
        (n, i) for n, i, _ in UNITREE_WEBRTC_CONTROLS
    ]
    assert all(a["reason"] for a in catalog() if not a["available"])
    assert {a["name"] for a in catalog() if not a["available"]} == PARAMETERIZED


def test_real_dimos_skill_dispatch_and_acknowledgement():
    c = Mock()
    c.publish_request.return_value = {"data": {"header": {"status": {"code": 0}}}}
    assert run(c)["ok"]
    c.publish_request.assert_called_once_with("rt/api/sport/request", {"api_id": 1016})


@pytest.mark.parametrize(
    "control",
    [
        {"mode": "teleop", "epoch": 3},
        {"mode": "idle", "epoch": 2},
        {"mode": "idle", "epoch": 3, "estop": True},
    ],
)
def test_control_changes_block_actions(control):
    c = Mock()
    with pytest.raises(ValueError):
        run(c, control=control)
    c.publish_request.assert_not_called()


@pytest.mark.parametrize("name", ["BodyHeight", "SpeedLevel", "Damp", "shell"])
def test_incomplete_or_unknown_requests_never_reach_robot(name):
    c = Mock()
    with pytest.raises(ValueError):
        run(c, name)
    c.publish_request.assert_not_called()


@pytest.mark.parametrize("reply", [{}, {"data": {"header": {"status": {"code": 7001}}}}])
def test_upstream_success_text_does_not_hide_a_missing_or_rejected_ack(reply):
    c = Mock()
    c.publish_request.return_value = reply
    with pytest.raises(ValueError):
        run(c)
    assert c.publish_request.call_count == 1


def test_replay_and_missing_confirmation_never_execute():
    c = Mock()
    with pytest.raises(ValueError):
        run(c, replay=True)
    with pytest.raises(ValueError):
        execute(c, "Hello", control={"mode": "idle", "epoch": 3}, epoch=3, confirmed="FrontJump")
    c.publish_request.assert_not_called()


def test_api_requires_connected_go2_and_idle_enabled_control(tmp_path):
    from fastapi.testclient import TestClient
    from go2_setup.api import create_app
    from go2_setup.config import Settings
    from go2_setup.profiles import profile

    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    s = app.state.supervisor
    s.call = Mock(return_value={"ok": True})
    body = {"name": "Hello", "confirmed": "Hello", "epoch": 3}
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/unitree/action", json=body, headers={"X-Go2-Request": "1"}
            ).status_code
            == 409
        )
        s.connection = "online"
        s.profile = profile("map-record")
        s.call = Mock(return_value={"ok": True})
        s.mode = "teleop"
        assert (
            client.post(
                "/api/unitree/action", json=body, headers={"X-Go2-Request": "1"}
            ).status_code
            == 409
        )
        s.call.assert_not_called()
        s.mode = "idle"
        assert (
            client.post(
                "/api/unitree/action", json=body, headers={"X-Go2-Request": "1"}
            ).status_code
            == 200
        )
        s.call.assert_called_once_with("/unitree/action", body, timeout=12)
        s.connection = "offline"
