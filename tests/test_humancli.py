import json
import stat
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from go2_setup.agent import NavigatorAgent, PROMPT
from go2_setup.agent_settings import AgentSettings
from go2_setup.agent_tools import capabilities, execute
from go2_setup.api import create_app
from go2_setup.config import Settings

KEY = "sk-test-private-key-must-not-leak"


def agent_at(tmp_path):
    s = SimpleNamespace(
        settings=Settings(root=tmp_path),
        target=object(),
        process=object(),
        mode="agent",
        connection="online",
        epoch=3,
        lock=threading.RLock(),
        session=None,
        telemetry={
            "camera": "fake-frame",
            "sensors": {"color_image": {"received": time.time()}},
            "pose": dict(x=0, y=0, yaw=0),
            "map": dict(width=100, height=100, resolution=0.1, origin=[-5, -5], cells=[0] * 10000),
        },
        call=Mock(return_value={"ok": True}),
    )
    a = NavigatorAgent(s)
    a.config.env = {}
    a.config.configure("openai", "test-model", KEY, vision=True)
    return a


@pytest.fixture
def fake_worker(monkeypatch):
    original = subprocess.Popen

    def launch(args, **kwargs):
        return original(
            [args[0], str(Path(__file__).with_name("agent_fixture_worker.py"))], **kwargs
        )

    monkeypatch.setattr("go2_setup.agent.subprocess.Popen", launch)


def wait_done(a, timeout=25):
    end = time.monotonic() + timeout
    while a.busy and time.monotonic() < end:
        time.sleep(0.03)
    assert not a.busy, a.snapshot()


def turn_for(a):
    turn = dict(
        conversation=a.conversation_id,
        context=a._context(),
        epoch=3,
        deadline=time.monotonic() + 120,
        cancel=threading.Event(),
        config=a.config.resolve(),
        space_id=None,
        moved=False,
        paused=False,
    )
    a.turn = turn
    return turn


def test_real_dimos_agent_loop_calls_guarded_tool_and_streams_result(tmp_path, fake_worker):
    a = agent_at(tmp_path)
    started = time.monotonic()
    a.submit("Please step back a meter", 3)
    assert time.monotonic() - started < 0.5  # API is asynchronous.
    wait_done(a)
    a.supervisor.call.assert_called_once_with(
        "/goal", {"epoch": 3, "x": -1.0, "y": pytest.approx(0)}
    )
    messages = a.snapshot()["messages"]
    assert any(m["role"] == "tool" and "move_relative" in m["text"] for m in messages)
    assert any(m["role"] == "assistant" and "accepted" in m["text"] for m in messages)
    assert a.history
    assert KEY not in json.dumps(a.snapshot())


def test_actual_dimos_image_followup_and_no_image_in_saved_history(tmp_path, fake_worker):
    a = agent_at(tmp_path)
    a.submit("Describe the camera", 3)
    wait_done(a)
    assert any("doorway" in m["text"] for m in a.snapshot()["messages"]), a.snapshot()
    assert "fake-frame" not in json.dumps(a.history)
    assert "fake-frame" not in json.dumps(a.snapshot())
    a.supervisor.call.assert_not_called()


def test_late_model_reply_cannot_move_after_mode_change(tmp_path, fake_worker):
    a = agent_at(tmp_path)
    a.submit("delayed back", 3)
    end = time.monotonic() + 20
    while not a.turn.get("agent_started") and time.monotonic() < end:
        time.sleep(0.03)
    assert a.turn.get("agent_started")
    a.supervisor.epoch = 4
    a.supervisor.mode = "teleop"
    wait_done(a)
    a.supervisor.call.assert_not_called()


def test_reset_cancels_worker_and_discards_late_replies(tmp_path, fake_worker):
    a = agent_at(tmp_path)
    a.submit("delayed back", 3)
    old = a.turn
    a.new_conversation()
    time.sleep(0.3)
    assert not a.snapshot()["messages"]
    assert old["cancel"].is_set()
    a.supervisor.call.assert_not_called()


def test_provider_errors_do_not_leak_credentials(tmp_path, fake_worker):
    a = agent_at(tmp_path)
    a.submit("error", 3)
    wait_done(a)
    transcript = json.dumps(a.snapshot())
    assert KEY not in transcript
    assert "could not complete" in transcript


def test_tools_require_unchanged_authority_and_one_motion_per_message(tmp_path):
    a = agent_at(tmp_path)
    t = turn_for(a)
    execute(a, t, "move_relative", {"direction": "left", "distance_m": 1})
    with pytest.raises(ValueError, match="one movement"):
        execute(a, t, "start_exploration", {})
    a.supervisor.epoch += 1
    with pytest.raises(ValueError, match="expired"):
        execute(a, t, "save_recording", {})
    assert a.supervisor.call.call_count == 1


def test_tool_schema_and_camera_permission_are_enforced(tmp_path):
    a = agent_at(tmp_path)
    t = turn_for(a)
    for args in [
        {"direction": "backward", "distance_m": 6},
        {"direction": "left", "distance_m": float("nan")},
        {"direction": "left", "distance_m": 1, "arbitrary": True},
    ]:
        with pytest.raises(ValueError):
            execute(a, t, "move_relative", args)
    a.config.configure("openai", "test-model", "", vision=False)
    with pytest.raises(ValueError, match="Enable vision"):
        execute(a, t, "camera_view", {})
    assert not any(x["name"] == "camera_view" for x in a.snapshot()["capabilities"])
    with pytest.raises(ValueError, match="not enabled"):
        execute(a, t, "shutdown", {})
    a.supervisor.call.assert_not_called()


def test_stop_is_immediate_without_llm_or_key(tmp_path):
    a = agent_at(tmp_path)
    a.config.configure("ollama", "test-local", vision=False)
    a.submit("stop", 3)
    assert not a.busy
    a.supervisor.call.assert_called_once_with("/agent/pause", {"epoch": 3}, timeout=20)


def test_history_expires_and_new_connection_starts_fresh(tmp_path):
    a = agent_at(tmp_path)
    a.messages = [{"role": "assistant", "text": "Old reply", "ts": time.time() - 86400}]
    a.history = [{"test": "old"}]
    a.last_activity -= 1801
    assert a.snapshot()["messages"] == []
    assert not a.history
    old = a.conversation_id
    a.supervisor.process = object()
    assert a.snapshot()["conversation_id"] != old


def test_config_precedence_legacy_key_and_private_storage(tmp_path):
    (tmp_path / "vision.json").write_text(json.dumps({"api_key": KEY, "enabled": True}))
    cfg = AgentSettings(tmp_path)
    cfg.env = {}
    assert cfg.resolve()["api_key"] == KEY
    assert cfg.status()["vision"]
    cfg.configure("openai", "new-model")
    assert stat.S_IMODE(cfg.path.stat().st_mode) == 0o600
    cfg.env = {"HUMANCLI_MODEL": "env-model", "OPENAI_API_KEY": "env-key"}
    assert cfg.resolve()["model"] == "env-model"
    assert cfg.resolve()["api_key"] == "env-key"
    assert "env-key" not in json.dumps(cfg.status())
    cfg.env = {}
    cfg.configure("openai", "other-model", base_url="https://example.com/v1")
    assert not cfg.resolve()["api_key"]  # No default-provider key forwarded.
    assert not cfg.resolve()["vision"]
    for url in [
        "http://external.example/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/?key=secret",
    ]:
        with pytest.raises(ValueError):
            cfg.configure("openai", "test", base_url=url)


def test_agent_api_guards_and_public_state(tmp_path):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "none"))
    app.state.agent.config.env = {}
    with TestClient(app) as client:
        for route in ["/api/agent/config", "/api/agent/cancel", "/api/agent/conversation"]:
            assert client.post(route, json={}).status_code == 403
        response = client.post(
            "/api/agent/config",
            headers={"X-Go2-Request": "1"},
            json={"provider": "openai", "model": "test", "api_key": KEY, "vision": False},
        )
        assert response.status_code == 200
        snapshot = client.get("/api/state").json()["agent"]
        assert snapshot["engine"] == "dimos-mcp"
        assert snapshot["capabilities"] == capabilities(False)
        assert KEY not in json.dumps(snapshot)
        assert "Always answer in English" in PROMPT


def test_record_explore_save_generate_workflow_uses_guarded_services(tmp_path):
    a = agent_at(tmp_path)
    a.supervisor.catalog = Mock()
    a.supervisor.catalog.list.return_value = [{"id": "segment-a", "status": "closed"}]
    a.supervisor.start_recording = Mock(return_value={"id": "session-a", "status": "recording"})
    a.supervisor.finish_recording = Mock(return_value={"id": "session-a", "status": "closed"})
    a.jobs = Mock()
    a.jobs.start.return_value = {"id": "map-a", "status": "queued"}
    t = turn_for(a)
    t["space_id"] = "office"
    execute(a, t, "start_recording", {})
    a.supervisor.start_recording.assert_called_once_with("office")
    execute(a, t, "start_exploration", {})
    with pytest.raises(ValueError, match="stop_navigation"):
        execute(a, t, "generate_map", {"segment_id": "segment-a"})
    execute(a, t, "stop_navigation", {})
    saved = execute(a, t, "save_recording", {})
    assert "segment-a" in json.dumps(saved)
    execute(a, t, "generate_map", {"segment_id": "segment-a"})
    a.jobs.start.assert_called_once_with("segment-a", 0.1, True)


def test_unknown_motion_outcome_cannot_be_retried_in_same_turn(tmp_path):
    a = agent_at(tmp_path)
    t = turn_for(a)
    a.supervisor.call.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        execute(a, t, "move_relative", {"direction": "forward", "distance_m": 1})
    with pytest.raises(ValueError, match="one movement"):
        execute(a, t, "move_relative", {"direction": "forward", "distance_m": 1})
    assert a.supervisor.call.call_count == 1


def test_navigation_pause_blocks_late_velocity_without_revoking_chat(monkeypatch):
    from go2_setup.modules import ControlGate
    from dimos.msgs.geometry_msgs.Twist import Twist

    monkeypatch.setattr("go2_setup.modules.Module.__init__", lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = time.monotonic()
    epoch = gate.switch("agent")
    gate.last_lidar = gate.last_map = time.monotonic()
    assert gate.navigation(epoch, True)
    gate._nav(Twist((0.1, 0, 0), (0, 0, 0)))
    assert gate.nav_forwarded == 1
    assert gate.navigation(epoch, False)
    gate._nav(Twist((0.1, 0, 0), (0, 0, 0)))
    assert gate.nav_forwarded == 1
    assert gate.heartbeat(epoch)
    assert gate.navigation(epoch, True)
    gate._nav(Twist((0.1, 0, 0), (0, 0, 0)))
    assert gate.nav_forwarded == 2
    gate.halt()
    assert not gate.navigation(epoch, True)


def test_ollama_model_tags_are_supported(tmp_path):
    cfg = AgentSettings(tmp_path)
    cfg.env = {}
    cfg.configure("ollama", "qwen3:8b")
    assert cfg.status()["model"] == "qwen3:8b"
    assert cfg.status()["configured"]
    with pytest.raises(ValueError, match="provider prefix"):
        cfg.configure("ollama", "ollama:qwen3:8b")
