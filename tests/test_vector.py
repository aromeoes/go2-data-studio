"""Embodiment boundary and safety tests. No physical robot is started."""

import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from go2_setup.profiles import profile, module_plan
from go2_setup.blueprints import base_profile
from go2_setup.robots import Robots
from go2_setup.vector.control import VectorController
from go2_setup.vector.tools import validate
from go2_setup.vector.credentials import load_credentials
from go2_setup.agent_tools import definitions
from go2_setup.api import create_app
from go2_setup.config import Settings


def pairing(tmp_path):
    cert = tmp_path / "robot.cert"
    cert.write_text("test-certificate")
    config = tmp_path / "sdk_config.ini"
    config.write_text(f"[abc123]\nname=Vector-TEST\ncert={cert}\nguid=private-robot-token\n")
    return str(config)


def driver():
    d = Mock()
    d.has_control.return_value = True
    d.sensor_state.return_value = dict(
        received=time.time(),
        cliff={"any_detected": False},
        picked_up=False,
        falling=False,
        proximity=dict(found_object=False, unobstructed=True, lift_in_fov=False, distance_mm=500),
        pose=dict(x=0, y=0, yaw=0, origin_id=1),
        faces=[],
    )
    return d


def controller():
    d = driver()
    c = VectorController(d, profile("assistant", kind="vector"))
    return c, d


def test_vector_profiles_and_robot_credentials_are_isolated(tmp_path):
    p = profile("assistant", kind="vector")
    assert not set(p["enabled"]) & {"lidar", "navigation", "mapping", "exploration", "recording"}
    assert profile("drive")["enabled"] == ["teleop", "camera"]
    with pytest.raises(ValueError):
        profile("map-record", kind="vector")
    with pytest.raises(ValueError):
        profile("assistant", ["voice"], kind="vector")
    robots = Robots(tmp_path)
    r = robots.save("Vector", "192.168.1.71", "abc123", "vector", sdk_config=pairing(tmp_path))
    assert r["profile"] == p
    assert "private-robot-token" not in json.dumps(robots.list())
    assert Robots(tmp_path).get(r["id"])["kind"] == "vector"
    assert load_credentials(r["sdk_config"], "ABC123")["name"] == "Vector-TEST"
    with pytest.raises(ValueError):
        robots.save("Other", "192.168.1.72", "def", "go2", ident=r["id"])


def test_dimensional_vector_blueprints_have_skills_and_no_go2_modules(monkeypatch):
    from go2_setup.vector.runtime import build_blueprint

    for preset in ("preview", "drive", "assistant"):
        config = profile(preset, kind="vector")
        bp = build_blueprint(config)
        names = {b.module.__name__ for b in bp.blueprints}
        assert {"VectorConnection", "VectorTelemetry", "ConsoleSDK"} <= names
        assert ("VectorSkills" in names) == (preset == "assistant")
        assert (
            not {"PassiveGo2Connection", "ControlGate", "VoxelGridMapper", "ReplanningAStarPlanner"}
            & names
        )
        assert len(names) == len(module_plan(config))


def test_teleop_clamps_treads_rejects_sideways_and_stops_on_stale_sensor():
    c, d = controller()
    epoch = c.switch("teleop")["epoch"]
    assert c.teleop(epoch, 2, 0, 0.5)
    left, right = d.wheels.call_args.args
    assert max(abs(left), abs(right)) <= 120 + 1e-10
    with pytest.raises(ValueError, match="sideways"):
        c.teleop(epoch, 0, 0.2, 0)
    d.sensor_state.return_value["received"] -= 2
    assert not c.teleop(epoch, 0.1, 0, 0)
    assert c.state()["mode"] == "idle"
    d.stop_motors.assert_called()


@pytest.mark.parametrize("field", ["cliff", "picked_up", "falling", "obstacle", "blocked_lift"])
def test_sensor_interlocks_reject_motion(field):
    c, d = controller()
    epoch = c.switch("teleop")["epoch"]
    s = d.sensor_state.return_value
    if field == "cliff":
        s["cliff"]["any_detected"] = True
    elif field == "obstacle":
        s["proximity"].update(found_object=True, distance_mm=50)
    elif field == "blocked_lift":
        s["proximity"]["lift_in_fov"] = True
    else:
        s[field] = True
    assert not c.teleop(epoch, 0.1, 0, 0)
    d.wheels.assert_not_called()


def test_stop_from_native_acquires_default_control_and_does_not_resume_personality():
    c, d = controller()
    assert c.state()["ownership"] == "native"
    c.halt(latch=True)
    d.acquire.assert_called_once()
    d.stop_motors.assert_called_once()
    d.release.assert_not_called()
    with pytest.raises(ValueError):
        c.native()
    c.authority.clear()
    c.native()
    d.release.assert_called_once()


def test_watchdog_and_old_epoch_cannot_resume_movement():
    c, d = controller()
    epoch = c.switch("teleop")["epoch"]
    c.teleop(epoch, 0.1, 0, 0)
    c.authority.deadline = 0
    c.tick()
    assert c.state()["mode"] == "idle"
    assert not c.teleop(epoch, 0.1, 0, 0)
    d.release.assert_not_called()


def test_head_only_person_search_and_default_priority_reaction():
    c, d = controller()
    c.switch("agent")
    c.action = {"status": "running"}
    c.owned = True
    d.has_control.return_value = False
    c.tick()
    assert c.action["status"] == "cancelled"
    assert (
        c.state()["mode"] == "agent"
    )  # Native wake-word reaction can finish; voice lease remains.
    assert not c.driving
    with pytest.raises(ValueError, match="native reaction"):
        c.start_action(c.authority.epoch, "speak", {"text": "hello"})


def test_runtime_action_inputs_are_bounded():
    for name, args in [
        ("move_relative", dict(direction="left", distance_m=0.3)),
        ("move_relative", dict(direction="forward", distance_m=5)),
        ("set_head", dict(angle_deg=float("nan"))),
        ("set_lift", dict(height=2)),
        ("play_expression", dict(expression="arbitrary_sdk_function")),
    ]:
        with pytest.raises(ValueError):
            validate(name, args)
    assert validate("move_relative", dict(direction="forward", distance_m=0.3))["distance_m"] == 0.3


def test_agent_advertises_vector_tools_not_go2_navigation():
    tools = {t["name"] for t in definitions(True, profile("assistant", kind="vector"))}
    assert {"move_relative", "set_head", "set_lift", "speak", "find_person", "camera_view"} <= tools
    assert not tools & {"start_exploration", "generate_map", "start_recording"}
    assert definitions(True, profile("drive", kind="vector")) == []
    assert "start_exploration" in {t["name"] for t in definitions(True, profile("assistant"))}


def test_vector_connect_profile_dispatch_and_go2_guard(tmp_path, monkeypatch):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    s = app.state.supervisor
    monkeypatch.setattr(s, "_launch", lambda: None)
    s.robots.save("Vector", "192.168.1.71", "abc123", "vector", sdk_config=pairing(tmp_path))
    with TestClient(app) as client:
        h = {"X-Go2-Request": "1"}
        ident = s.robots.list()[0]["id"]
        assert client.post("/api/connect", headers=h, json={"robot_id": ident}).status_code == 200
        assert s.profile == base_profile("vector")
        assert s.mode == "idle"
        s.connection = "online"
        s.call = Mock(return_value={})
        assert client.post("/api/mode", headers=h, json={"mode": "explore"}).status_code == 409
        assert (
            client.post(
                "/api/session/modules",
                headers=h,
                json={
                    "robot_id": ident,
                    "preset": "custom",
                    "modules": ["VectorConnection", "RelayBridgeModule", "VectorTelemetry", "McpClient", "VectorSkills"],
                },
            ).status_code
            == 200
        )
        assert s.target["kind"] == "vector" and s.mode == "idle"
        assert client.post("/api/disconnect", headers=h).status_code == 200


def test_wirepod_token_only_authorizes_voice_and_deduplicates(tmp_path, monkeypatch):
    app = create_app(
        Settings(root=tmp_path, desktop_token="desktop-test", env_file=tmp_path / "absent")
    )
    s, a, voice = app.state.supervisor, app.state.agent, app.state.wirepod
    monkeypatch.setattr(s, "_launch", lambda: None)
    voice.enable()
    with TestClient(app) as client:
        h = {"Authorization": "Bearer " + voice.token, "X-Go2-Request": "1"}
        assert client.get("/api/state", headers=h).status_code == 403
        assert client.post("/api/mode", headers=h, json={"mode": "agent"}).status_code == 403
        assert client.get("/api/vector/wirepod/session", headers=h).status_code == 409
        s.target = {"kind": "vector", "serial": "abc123", "replay": None}
        s.profile, s.connection, s.mode, s.epoch, s.robot_id = (
            profile("assistant", kind="vector"),
            "online",
            "agent",
            4,
            "robot",
        )
        a.submit = Mock(return_value={"accepted": True})
        session = client.get("/api/vector/wirepod/session", headers=h).json()
        payload = {**session, "id": "unique", "text": "look up"}
        assert (
            client.post("/api/vector/wirepod/transcript", headers=h, json=payload).status_code
            == 200
        )
        assert (
            client.post("/api/vector/wirepod/transcript", headers=h, json=payload).status_code
            == 409
        )
        s.epoch += 1
        assert (
            client.post(
                "/api/vector/wirepod/transcript", headers=h, json={**payload, "id": "late"}
            ).status_code
            == 409
        )
        a.submit.assert_called_once()
        s.target, s.connection = None, "offline"


def test_delayed_wheel_commands_are_cancelled_not_queued():
    from concurrent.futures import Future
    from go2_setup.vector.driver import VectorDriver

    d = VectorDriver("192.168.1.71", "fixture", "unused", profile("drive", kind="vector"))
    pending = Future()
    d.robot = Mock()
    d.robot.motors.set_wheel_motors.return_value = pending
    d.wheels(50, 50)
    d.wheels(50, 50)  # Do not queue duplicate input during a brief network delay.
    assert d.robot.motors.set_wheel_motors.call_count == 1
    d.wheel_sent_at -= 0.21
    with pytest.raises(ValueError, match="acknowledgement delayed"):
        d.wheels(50, 50)
    assert pending.cancelled()
    assert d.robot.motors.set_wheel_motors.call_count == 1


def test_agent_actions_yield_for_native_wake_word_and_stop_retains_control():
    from concurrent.futures import Future

    c, d = controller()
    epoch = c.switch("agent")["epoch"]
    d.acquire.assert_not_called()
    pending = Future()
    d.action.return_value = pending
    c.start_action(epoch, "speak", {"text": "hello"})
    end = time.monotonic() + 1
    while not d.action.called and time.monotonic() < end:
        time.sleep(0.01)
    pending.set_result(None)
    while c.state()["action"]["status"] == "running" and time.monotonic() < end:
        time.sleep(0.01)
    assert c.state()["action"]["status"] == "completed"
    d.release.assert_called_once()
    assert c.state()["ownership"] == "native"
    c.halt(latch=True)
    assert c.state()["ownership"] == "stopped"
    assert d.release.call_count == 1


def test_sensor_stream_remains_live_before_camera_first_frame():
    from types import SimpleNamespace
    from go2_setup.vector.modules import VectorConnection

    d = driver()
    d.latest_image = None
    d.triggers = set()
    d.sensor_state.return_value['power'] = None
    done = Mock()
    done.wait.side_effect = [False, True]
    connection = SimpleNamespace(
        done=done, driver=d, count=0, odom=Mock(), color_image=Mock(),
        vector_state=Mock(), profile=profile('preview', kind='vector'),
        last_image=None, camera=None, camera_received=0,
    )
    VectorConnection._publish(connection)
    payload = json.loads(connection.vector_state.publish.call_args.args[0])
    assert payload['vector']['received'] > 0
    assert payload['sensors']['odom']['count'] == 1
    assert payload['camera'] is None
    connection.color_image.publish.assert_not_called()


def test_vector_camera_stop_closes_blocked_rpc_without_waiting_for_an_image():
    import asyncio
    from types import SimpleNamespace
    from go2_setup.vector.camera import prepare_camera

    async def exercise():
        entered, closed = asyncio.Event(), asyncio.Event()
        class Stream:
            async def __aenter__(self):
                entered.set()
                return self
            async def __aexit__(self, *args):
                closed.set()
            def __aiter__(self):
                return self
            async def __anext__(self):
                await asyncio.Event().wait()
        camera = SimpleNamespace(
            grpc_interface=SimpleNamespace(CameraFeed=SimpleNamespace(with_scope=lambda _: Stream())),
            _enabled=True, _camera_feed_task=None, _unpack_image=Mock(),
        )
        pending = []
        def run(coro):
            pending.append(coro)
            return Mock()
        prepare_camera(camera, lambda: object(), run)
        camera._camera_feed_task = asyncio.create_task(camera._request_and_handle_images())
        await asyncio.wait_for(entered.wait(), 1)
        camera.close_camera_feed()
        await asyncio.wait_for(pending.pop(), 1)
        assert closed.is_set() and camera._camera_feed_task is None
        camera._unpack_image.assert_not_called()
    asyncio.run(exercise())


def test_release_backward_sends_stop_even_if_driver_reports_a_fault():
    c, d = controller()
    epoch = c.switch("teleop")["epoch"]
    assert c.teleop(epoch, -0.1, 0, 0)
    d.has_control.return_value = False  # For example a failed drive acknowledgement.
    d.stop_motors.reset_mock()
    assert c.teleop(epoch, 0, 0, 0)
    d.stop_motors.assert_called_once()
    assert not c.driving and not c.stop_pending
    # No acceleration-limited DriveWheels(0, 0) command is used for release.
    assert d.wheels.call_args.args == (-100, -100)


def test_idle_watchdog_retries_stop_after_transport_failure():
    c, d = controller()
    c.switch("teleop")
    d.has_control.return_value = False
    d.stop_motors.side_effect = [TimeoutError("pending stop"), None]
    with pytest.raises(TimeoutError):
        c.halt(latch=True)
    assert c.stop_pending and c.authority.estop
    assert c.authority.mode == "idle"
    c.tick()
    assert not c.stop_pending
    assert c.authority.estop  # Retry must not re-enable movement.


def test_driver_release_cancels_pending_drive_and_uses_stop_rpc():
    from concurrent.futures import Future
    from go2_setup.vector.driver import VectorDriver
    d = VectorDriver("192.168.1.71", "fixture", "unused", profile("drive", kind="vector"))
    d.robot = Mock()
    drive, stop = Future(), Future()
    d.robot.motors.set_wheel_motors.return_value = drive
    d.robot.motors.stop_all_motors.return_value = stop
    stop.set_result(None)
    d.wheels(-100, -100)
    d.motion_error = "drive fault"
    d.stop_motors()
    assert drive.cancelled()
    d.robot.motors.stop_all_motors.assert_called_once()
    assert d.wheel_future is None


def test_motor_acknowledgement_is_separate_from_action_completion():
    from types import SimpleNamespace
    from go2_setup.vector.driver import VectorDriver
    descriptor = SimpleNamespace(enum_type=SimpleNamespace(values_by_number={
        1: SimpleNamespace(name="RESPONSE_RECEIVED"),
        2: SimpleNamespace(name="REQUEST_PROCESSING"),
        3: SimpleNamespace(name="OK"),
        100: SimpleNamespace(name="FORBIDDEN"),
    }))
    status = SimpleNamespace(code=1, DESCRIPTOR=SimpleNamespace(fields_by_name={"code": descriptor}))
    response = SimpleNamespace(status=status, DESCRIPTOR=SimpleNamespace(fields_by_name={"status": SimpleNamespace(enum_type=None)}))
    VectorDriver.validate_motor_response(response)
    with pytest.raises(ValueError):
        VectorDriver.validate_result(response)
    status.code = 2
    VectorDriver.validate_motor_response(response)
    with pytest.raises(ValueError):
        VectorDriver.validate_result(response)
    status.code = 3
    VectorDriver.validate_motor_response(response)
    status.code = 100
    with pytest.raises(ValueError):
        VectorDriver.validate_motor_response(response)


def test_camera_recovers_stalled_first_frame_without_motor_control():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock
    from go2_setup.vector.camera import prepare_camera

    async def scenario():
        opened, closed = [], []
        delivered = asyncio.Event()
        class Stream:
            async def __aenter__(self):
                opened.append(self)
                return self
            async def __aexit__(self, *_):
                closed.append(self)
            def __aiter__(self):
                return self
            async def __anext__(self):
                if len(opened) == 1:
                    await asyncio.Event().wait()
                return 'image'
        camera = SimpleNamespace(
            grpc_interface=SimpleNamespace(CameraFeed=SimpleNamespace(with_scope=lambda _: Stream())),
            _enabled=True, _camera_feed_task=None,
        )
        def unpack(message):
            assert message == 'image'
            camera._enabled = False
            delivered.set()
        camera._unpack_image = Mock(side_effect=unpack)
        prepare_camera(camera, lambda: object(), Mock(), frame_timeout=0.01, first_frame_timeout=0.01, retry_delay=0)
        task = asyncio.create_task(camera._request_and_handle_images())
        await asyncio.wait_for(delivered.wait(), timeout=1)
        await asyncio.wait_for(task, timeout=1)
        assert len(opened) == len(closed) == 2
        camera._unpack_image.assert_called_once_with('image')
    asyncio.run(scenario())


def test_failed_sdk_startup_closes_transport_without_using_uninitialized_viewer():
    from types import SimpleNamespace
    from go2_setup.vector.driver import VectorDriver
    from unittest.mock import Mock
    channel, thread = Mock(), Mock()
    conn = SimpleNamespace(_loop=SimpleNamespace(is_closed=lambda: True),
                           _channel=SimpleNamespace(_channel=channel), _thread=thread)
    robot = SimpleNamespace(conn=conn, disconnect=Mock(side_effect=AssertionError("no viewer")))
    VectorDriver._close_failed_connection(robot)
    channel.close.assert_called_once()
    thread.join.assert_called_once_with(timeout=1)
    robot.disconnect.assert_not_called()


def test_sdk_pairing_renewal_uses_pinned_tls_and_saves_bytes_token_privately(tmp_path, monkeypatch):
    from pathlib import Path
    import base64
    import configparser
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import grpc
    from go2_setup.vector.credentials import renew_credentials
    config = pairing(tmp_path)
    new_token = base64.b64encode(b'0123456789abcdef')
    rpc = Mock(return_value=SimpleNamespace(code=1, client_token_guid=new_token))
    protocol = SimpleNamespace(UserAuthenticationResponse=SimpleNamespace(AUTHORIZED=1),
                               UserAuthenticationRequest=lambda **kw: kw)
    monkeypatch.setitem(sys.modules, 'anki_vector.messaging', SimpleNamespace(
        client=SimpleNamespace(ExternalInterfaceStub=lambda _: SimpleNamespace(UserAuthentication=rpc)), protocol=protocol))
    tls = Mock(return_value='pinned-tls')
    secure = MagicMock()
    monkeypatch.setattr(grpc, 'ssl_channel_credentials', tls)
    monkeypatch.setattr(grpc, 'secure_channel', secure)
    result = renew_credentials(config, 'abc123', '192.168.1.71')
    assert result['guid'] == new_token.decode()
    tls.assert_called_once_with(root_certificates=b'test-certificate')
    secure.assert_called_once_with('192.168.1.71:443', 'pinned-tls', options=(('grpc.ssl_target_name_override', 'Vector-TEST'),))
    assert rpc.call_args.kwargs == {'timeout': 15}
    assert rpc.call_args.args[0]['user_session_id'] == b'private-robot-token'
    assert Path(config).stat().st_mode & 0o777 == 0o600
    saved = configparser.ConfigParser()
    saved.read(config)
    assert saved['abc123']['name'] == 'Vector-TEST'


def test_authentication_failure_renews_only_once_and_never_logs_secrets(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from go2_setup.vector import driver as module
    from go2_setup.vector.errors import read_startup_error
    error_type = type('VectorUnauthenticatedException', (Exception,), {})
    robots = []
    def robot(**kwargs):
        r = Mock()
        r.connect.side_effect = error_type('private-credential-must-not-escape')
        robots.append(r)
        return r
    monkeypatch.setitem(sys.modules, 'anki_vector', SimpleNamespace(AsyncRobot=robot, util=SimpleNamespace(read_configuration=Mock())))
    monkeypatch.setitem(sys.modules, 'anki_vector.events', SimpleNamespace(Events=SimpleNamespace(robot_state='state')))
    monkeypatch.setattr(module, 'load_credentials', lambda *a: {})
    renew = Mock()
    monkeypatch.setattr(module, 'renew_credentials', renew)
    monkeypatch.setattr(module.VectorDriver, '_close_failed_connection', Mock())
    error_file = tmp_path / 'startup.json'
    monkeypatch.setenv('VECTOR_STARTUP_ERROR_FILE', str(error_file))
    d = module.VectorDriver('192.168.1.71', 'abc123', 'config.ini', {'enabled': []})
    with pytest.raises(ValueError, match='rejected its SDK pairing') as caught:
        d.connect()
    assert len(robots) == 2
    renew.assert_called_once_with('config.ini', 'abc123', '192.168.1.71')
    assert 'private-credential' not in str(caught.value)
    assert 'private-credential' not in error_file.read_text()
    assert read_startup_error(error_file) == str(caught.value)
    assert d.robot is None
    d.close()


def test_camera_gives_first_frame_longer_than_active_stream_timeout():
    import asyncio
    from types import SimpleNamespace
    from go2_setup.vector.camera import prepare_camera
    async def scenario():
        opens = []
        class Stream:
            async def __aenter__(self):
                opens.append(self)
                return self
            async def __aexit__(self, *_):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                await asyncio.sleep(0.03)
                return 'first-image'
        camera = SimpleNamespace(grpc_interface=SimpleNamespace(CameraFeed=SimpleNamespace(with_scope=lambda _: Stream())), _enabled=True)
        def unpack(message):
            assert message == 'first-image'
            camera._enabled = False
        camera._unpack_image = Mock(side_effect=unpack)
        prepare_camera(camera, lambda: object(), Mock(), frame_timeout=0.01, first_frame_timeout=0.1)
        await asyncio.wait_for(camera._request_and_handle_images(), timeout=1)
        assert len(opens) == 1
        camera._unpack_image.assert_called_once()
    asyncio.run(scenario())


def test_camera_enables_image_streaming_before_each_subscription():
    import asyncio
    from types import SimpleNamespace
    from go2_setup.vector.camera import prepare_camera
    async def scenario():
        calls = []
        class Stream:
            async def __aenter__(self):
                calls.append('subscribe')
                return self
            async def __aexit__(self, *_):
                calls.append('close')
            def __aiter__(self):
                return self
            async def __anext__(self):
                if calls.count('subscribe') == 1:
                    raise StopAsyncIteration()
                return 'image'
        async def enable(request):
            assert request == {'enable': True}
            calls.append('enable')
        camera = SimpleNamespace(grpc_interface=SimpleNamespace(
            CameraFeed=SimpleNamespace(with_scope=lambda _: Stream()), EnableImageStreaming=enable), _enabled=True)
        def unpack(_):
            camera._enabled = False
        camera._unpack_image = unpack
        prepare_camera(camera, lambda: object(), Mock(), enable_request=lambda **kw: kw, retry_delay=0)
        await asyncio.wait_for(camera._request_and_handle_images(), timeout=1)
        assert calls == ['enable', 'subscribe', 'close', 'enable', 'subscribe', 'close']
        assert camera._studio_feed_status['frames'] == 1
        assert camera._studio_feed_status['error'] is None
    asyncio.run(scenario())


@pytest.mark.parametrize('block', ['obstacle', 'lift', 'unknown'])
def test_forward_block_keeps_teleop_for_reverse_and_turn_without_new_l1_press(block):
    c, d = controller()
    epoch = c.switch('teleop')['epoch']
    assert c.teleop(epoch, .08, 0, 0)
    p = d.sensor_state.return_value['proximity']
    if block == 'obstacle':
        p.update(found_object=True, unobstructed=False, distance_mm=30)
    elif block == 'lift':
        p['lift_in_fov'] = True
    else:
        p.update(found_object=False, unobstructed=False)
    d.wheels.reset_mock()
    d.stop_motors.reset_mock()
    assert not c.teleop(epoch, .08, 0, .1)
    assert not c.teleop(epoch, .08, 0, .1)
    d.wheels.assert_not_called()
    d.stop_motors.assert_called_once()
    assert c.state()['mode'] == 'teleop' and c.state()['epoch'] == epoch
    assert not c.driving and 'Back up or turn' in c.state()['stop_reason']
    assert c.teleop(epoch, -.08, 0, 0)
    assert all(v < 0 for v in d.wheels.call_args.args)
    assert c.state()['stop_reason'] is None
    assert c.teleop(epoch, 0, 0, .1)
    left, right = d.wheels.call_args.args
    assert left < 0 < right
    d.sensor_state.return_value['cliff']['any_detected'] = True
    assert not c.teleop(epoch, -.08, 0, 0)
    assert c.state()['mode'] == 'idle' and c.state()['epoch'] != epoch
    assert not c.teleop(epoch, 0, 0, .1)


def test_vector_turns_in_place_and_clamps_combined_drive():
    c, d = controller()
    epoch = c.switch('teleop')['epoch']
    assert c.teleop(epoch, 0, 0, 1.5)
    assert d.wheels.call_args.args == (-52.5, 52.5)
    assert c.teleop(epoch, 0, 0, -1.5)
    assert d.wheels.call_args.args == (52.5, -52.5)
    assert c.teleop(epoch, 0.12, 0, 100)
    left, right = d.wheels.call_args.args
    assert 0 < left < right <= 120
    assert c.teleop(epoch, 0, 0, 0)
    d.stop_motors.assert_called()


def test_repeated_acquisition_reuses_granted_sdk_control(monkeypatch):
    import sys
    from types import SimpleNamespace
    from go2_setup.vector.driver import VectorDriver

    priority = object()
    monkeypatch.setitem(sys.modules, 'anki_vector.connection', SimpleNamespace(
        ControlPriorityLevel=SimpleNamespace(DEFAULT_PRIORITY=priority)))
    d = VectorDriver('test', 'test', 'test', {'enabled': ['faces']})
    d.robot = Mock()
    d.robot.conn.control_granted_event.is_set.return_value = True
    d.acquire()
    d.acquire()
    d.robot.conn.request_control.assert_not_called()
    d.robot.vision.enable_face_detection.assert_called_once_with(detect_faces=True)
    # Losing ownership must negotiate again, even after a healthy prior lease.
    d.robot.conn.control_granted_event.is_set.return_value = False
    d.acquire()
    d.robot.conn.request_control.assert_called_once_with(priority, timeout=3)
    assert d.robot.vision.enable_face_detection.call_count == 2
    assert d.transport['acquire_ms'] >= 0
