import asyncio
import base64
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from go2_setup.robot_skills import (
    Places,
    NamedNavigation,
    Patrol,
    CPUTracker,
    RobotSkills,
    RobotSpeech,
    pose_message,
    grid_message,
    follow_corridor_clear,
)
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat


def snapshot():
    stamp = time.time()
    return {
        "pose": {"x": 0, "y": 0, "yaw": 0.5},
        "sensors": {n: {"received": stamp} for n in ("odom", "lidar", "color_image")},
        "map": {
            "cells": [0] * 10000,
            "width": 100,
            "height": 100,
            "resolution": 0.1,
            "origin": [-5, -5],
            "received": stamp,
        },
    }


def test_real_dimos_tag_and_named_navigation_persist_with_frame_guard(tmp_path):
    places = Places(tmp_path, "frame-one")
    places.space = "office"
    places.yaw = 0.5
    owner = SimpleNamespace(places=places, send_goal=Mock(return_value=True))
    navigation = NamedNavigation(owner)
    navigation._latest_odom = pose_message(snapshot()["pose"])
    assert "Tagged" in navigation.tag_location("Tule's desk")
    message = navigation.navigate_with_text("tule's desk")
    assert "accepted" in message
    goal = owner.send_goal.call_args.args[0]
    assert goal.frame_id == "world"
    assert goal.orientation.to_euler().z == pytest.approx(0.5)
    reloaded = Places(tmp_path, "frame-two")
    reloaded.space = "office"
    assert reloaded.list() == [{"name": "Tule's desk", "usable": False}]
    with pytest.raises(ValueError, match="earlier connection"):
        reloaded.query_tagged_location("Tule's desk")
    reloaded.space = "other-office"
    assert reloaded.query_tagged_location("Tule's desk") is None


def test_follow_corridor_rejects_stale_unknown_and_obstacle_data():
    snap = snapshot()
    assert follow_corridor_clear(snap, 0.3, 0)
    snap["sensors"]["color_image"]["received"] -= 2
    assert not follow_corridor_clear(snap, 0.3, 0)
    snap = snapshot()
    snap["map"]["cells"][50 * 100 + 52] = 100
    assert not follow_corridor_clear(snap, 0.3, 0)
    snap["map"]["cells"][50 * 100 + 52] = -1
    assert not follow_corridor_clear(snap, 0.3, 0)


def test_real_cpu_tracker_handles_duplicate_frames_and_invalid_boxes():
    data = np.random.default_rng(1).integers(0, 255, (160, 240, 3), dtype=np.uint8)
    image = Image(data=data, format=ImageFormat.BGR)
    tracker = CPUTracker()
    assert len(tracker.init_track(image, [50, 30, 110, 130])) == 1
    assert len(tracker.process_image(image)) == 1
    assert len(tracker.process_image(Image(data=data.copy(), format=ImageFormat.BGR))) == 1
    for box in [[0, 0, float("nan"), 1], [-1, 0, 5, 10], [0, 0, 500, 300]]:
        with pytest.raises(ValueError, match="bounding box"):
            tracker.init_track(image, box)


def test_real_dimos_patrol_selects_goal_and_restores_planner_on_stop():
    async def run():
        owner = SimpleNamespace(planner=Mock(), send_goal=Mock(return_value=True))
        patrol = Patrol(owner)
        await patrol.handle_odom(pose_message(snapshot()["pose"]))
        await patrol.handle_global_costmap(grid_message(snapshot()["map"]))
        assert "started" in await patrol.begin(snapshot())
        await asyncio.sleep(0.15)
        owner.send_goal.assert_called()
        assert patrol.is_patrolling()
        before = owner.send_goal.call_count
        await patrol.stop_patrol()
        assert not patrol.is_patrolling()
        assert owner.send_goal.call_count == before  # No late current-pose goal.
        owner.planner.set_replanning_enabled.assert_called_with(True)
        owner.planner.reset_safe_goal_clearance.assert_called()

    asyncio.run(run())


@pytest.fixture
def runtime(tmp_path):
    control = {"epoch": 3, "mode": "agent", "estop": False, "navigation_enabled": False}
    gate = Mock()
    gate.state.side_effect = lambda: dict(control)

    def navigation(epoch, enabled):
        if epoch != control["epoch"] or control["mode"] != "agent":
            return False
        control["navigation_enabled"] = enabled
        return True

    gate.navigation.side_effect = navigation
    planner = Mock()
    planner.set_goal.return_value = True
    planner.is_goal_reached.return_value = False
    snap = snapshot()
    bridge = Mock()
    bridge.snapshot.side_effect = lambda: snap
    skills = RobotSkills(tmp_path, gate, planner, bridge, Mock())
    skills.config.env = {}
    try:
        yield skills, control, snap
    finally:
        gate.navigation(3, False)
        skills.close()


def wait_for(condition, timeout=4):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if condition():
            return
        time.sleep(0.02)
    assert condition()


def test_runtime_patrol_does_not_deadlock_and_stops_on_control_takeover(runtime):
    skills, control, _ = runtime
    result = skills.call("start_patrol", {}, 3)
    assert result["accepted"] and not result["completed"]
    wait_for(lambda: skills.planner.set_goal.called)
    control.update(epoch=4, mode="teleop", navigation_enabled=False)
    wait_for(lambda: skills.state()["active"] is None)
    assert skills.state()["phase"] == "idle"


def test_old_epoch_and_missing_named_place_never_set_goal(runtime):
    skills, _, _ = runtime
    with pytest.raises(ValueError, match="expired"):
        skills.call("start_patrol", {}, 2)
    skills.call("navigate_with_text", {"query": "unknown"}, 3, "office")
    wait_for(lambda: skills.state()["phase"] == "error")
    skills.planner.set_goal.assert_not_called()
    assert "No current-session" in skills.state()["message"]


def test_delayed_speech_is_invalid_after_stop_and_new_generation(runtime):
    skills, _, _ = runtime
    skills.epoch = 3
    speech = RobotSpeech(skills)
    skills.stop()
    skills.cancel_event = threading.Event()
    with pytest.raises(ValueError, match="cancelled"):
        speech.request("audio", {})
    skills.connection.publish_request.assert_not_called()


def test_stop_closes_navigation_and_never_changes_posture(runtime):
    skills, control, _ = runtime
    skills.call("stop_following", {}, 3)
    assert not control["navigation_enabled"]
    skills.planner.cancel_goal.assert_called_once()
    skills.connection.assert_not_called()


def test_follow_uses_vision_setting_and_never_downloads_gpu_models(runtime):
    skills, _, snap = runtime
    ok, encoded = cv2.imencode(".jpg", np.zeros((160, 240, 3), np.uint8))
    assert ok
    snap["camera"] = base64.b64encode(encoded).decode()
    skills.call("follow_person", {"query": "the person"}, 3)
    wait_for(lambda: skills.state()["phase"] == "error")
    assert "OpenAI" in skills.state()["message"]
    skills.gate.skill_velocity.assert_not_called()


def test_real_follow_skill_uses_cpu_tracker_and_guarded_velocity(runtime):
    from go2_setup.robot_skills import Follow

    skills, control, snap = runtime
    skills.epoch = 3
    control["navigation_enabled"] = True
    data = np.random.default_rng(9).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    image = Image(data=data, format=ImageFormat.BGR)
    follower = Follow(skills)
    skills.follow = follower
    follower._latest_image = image
    message = follower.follow_person("the person", initial_bbox=[250, 70, 370, 320])
    assert "Starting to follow" in message
    wait_for(lambda: skills.gate.skill_velocity.called)
    assert all(call.args[0] == 3 for call in skills.gate.skill_velocity.call_args_list)
    control["navigation_enabled"] = False
    skills.stop()
    count = skills.gate.skill_velocity.call_count
    time.sleep(0.2)
    assert skills.gate.skill_velocity.call_count == count


def test_audio_uses_dimos_tts_and_robot_bridge_without_computer_speaker(runtime, monkeypatch):
    from reactivex import Subject
    from dimos.stream.audio.base import AudioEvent
    from unitree_webrtc_connect.constants import AUDIO_API, RTC_TOPIC

    skills, _, _ = runtime
    skills.epoch = 3
    skills.config.configure("openai", "test-model", "test-private-key", vision=True)
    skills.connection.publish_request.return_value = {"data": {"header": {"status": {"code": 0}}}}
    subject = Subject()
    node = Mock()
    node.emit_audio.return_value = subject
    node._synthesize_speech.side_effect = lambda text: subject.on_next(
        AudioEvent(
            data=np.ones(48, dtype=np.float32) * 0.1,
            sample_rate=24000,
            timestamp=time.time(),
            channels=1,
        )
    )
    factory = Mock(return_value=node)
    monkeypatch.setattr("dimos.stream.audio.tts.node_openai.OpenAITTSNode", factory)
    message = RobotSpeech(skills).speak("Hello")
    assert "Go2 speaker" in message
    ids = [c.args[1]["api_id"] for c in skills.connection.publish_request.call_args_list]
    assert AUDIO_API["ENTER_MEGAPHONE"] in ids
    assert AUDIO_API["UPLOAD_MEGAPHONE"] in ids
    assert ids[-1] == AUDIO_API["EXIT_MEGAPHONE"]
    assert all(
        c.args[0] == RTC_TOPIC["AUDIO_HUB_REQ"]
        for c in skills.connection.publish_request.call_args_list
    )
    node.dispose.assert_called_once()
    assert "test-private-key" not in str(skills.state())


def test_missing_speaker_ack_does_not_claim_success(runtime):
    skills, _, _ = runtime
    skills.epoch = 3
    skills.connection.publish_request.return_value = {}
    with pytest.raises(ValueError, match="acknowledge"):
        skills.audio_request("audio", {})


def test_new_skills_are_filtered_by_profile_and_vision_and_guarded(tmp_path):
    from go2_setup.agent_tools import definitions, execute
    from go2_setup.profiles import profile
    from test_humancli import agent_at, turn_for

    config = profile("assistant")
    names = {item["name"] for item in definitions(True, config)}
    assert {"tag_location", "navigate_with_text", "start_patrol", "follow_person", "speak"} <= names
    assert "follow_person" not in {item["name"] for item in definitions(False, config)}
    assert "start_patrol" not in {item["name"] for item in definitions(True, profile("map-record"))}
    agent = agent_at(tmp_path)
    agent.supervisor.profile = config
    turn = turn_for(agent)
    execute(agent, turn, "start_patrol", {})
    agent.supervisor.call.assert_called_once_with(
        "/skills/call",
        {"name": "start_patrol", "arguments": {}, "epoch": 3, "space_id": None},
        timeout=12,
    )
    with pytest.raises(ValueError, match="one movement"):
        execute(agent, turn, "follow_person", {"query": "the person"})


def test_skill_velocity_rejects_old_epochs_even_if_new_navigation_is_active(monkeypatch):
    from go2_setup.modules import ControlGate

    monkeypatch.setattr("go2_setup.modules.Module.__init__", lambda self, **kwargs: None)
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = time.monotonic()
    epoch = gate.switch("agent")
    gate.navigation(epoch, True)
    assert gate.skill_velocity(epoch, 0.1, 0, 0)
    gate.halt()
    newer = gate.switch("agent")
    gate.navigation(newer, True)
    count = gate.cmd_vel.publish.call_count
    assert not gate.skill_velocity(epoch, 0.1, 0, 0)
    assert gate.cmd_vel.publish.call_count == count


def test_delayed_person_detection_cannot_restart_after_stop(runtime, monkeypatch):
    skills, control, snap = runtime
    skills.config.configure("openai", "test-model", "test-private-key", vision=True)
    ok, encoded = cv2.imencode(".jpg", np.zeros((360, 640, 3), np.uint8))
    assert ok
    snap["camera"] = base64.b64encode(encoded).decode()
    started, release = threading.Event(), threading.Event()

    def detect(*args):
        started.set()
        release.wait(3)
        return [200, 30, 400, 300]

    monkeypatch.setattr("dimos.models.vl.openai.OpenAIVlModel", Mock())
    monkeypatch.setattr("dimos.navigation.visual.query.get_object_bbox_from_image", detect)
    skills.call("follow_person", {"query": "the person"}, 3)
    assert started.wait(2)
    skills.gate.navigation(3, False)
    skills.stop()
    control.update(epoch=4, mode="teleop")
    release.set()
    skills.worker.join(timeout=3)
    assert not skills.worker.is_alive()
    skills.gate.skill_velocity.assert_not_called()
    skills.planner.set_goal.assert_not_called()
    assert skills.state()["active"] is None
