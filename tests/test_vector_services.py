"""Local voice services stay separate from both robot control and Go2."""
from types import SimpleNamespace
import base64
import hashlib
import json

import pytest
import threading
from unittest.mock import Mock

from fastapi.testclient import TestClient
from go2_setup.api import create_app
from go2_setup.config import Settings
from go2_setup.vector.services import VectorServices, preserve_app_tokens


def service(tmp_path):
    supervisor = SimpleNamespace(lock=threading.RLock(), target=None)
    voice = Mock(path=tmp_path / "voice-token")
    return VectorServices(Settings(root=tmp_path), supervisor, voice, Mock(), bundle=tmp_path / "bundle")


def target():
    return dict(kind="vector", ip="192.168.1.71", serial="abc123", sdk_config="not-used", replay=None)


def test_go2_replay_and_disconnected_never_start_wirepod(tmp_path):
    services = service(tmp_path)
    services.validate_bundle = Mock(side_effect=AssertionError("must not inspect/start runtime"))
    for t in [None, dict(kind="go2"), dict(kind="vector", replay="dataset")]:
        services.reconcile(t)
        assert services.status()["state"] == "stopped"
    services.validate_bundle.assert_not_called()


def test_switching_robot_or_disconnect_terminates_only_owned_child(tmp_path):
    services = service(tmp_path)
    child = Mock()
    child.poll.return_value = None
    services.child = child
    services.active = ("abc123", "192.168.1.71", "not-used")
    services.reconcile(dict(kind="go2"))
    child.terminate.assert_called_once()
    child.kill.assert_not_called()
    assert services.child is None


def test_missing_bundle_does_not_break_robot_session(tmp_path):
    services = service(tmp_path)
    services.reconcile(target())
    assert services.status()["state"] == "missing_runtime"
    assert services.child is None


def test_remote_host_conflict_prevents_advertising_or_launch(tmp_path, monkeypatch):
    services = service(tmp_path)
    services.validate_bundle = Mock()
    services.prepare = Mock()
    monkeypatch.setattr("go2_setup.vector.services.host_address", lambda _: "192.168.1.2")
    monkeypatch.setattr("go2_setup.vector.services.subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b'{"hosts":["192.168.1.67"]}'))
    services.reconcile(target())
    assert services.status()["state"] == "conflict"
    services.prepare.assert_not_called()
    assert services.child is None


def test_subprocess_does_not_inherit_app_credentials(tmp_path, monkeypatch):
    services = service(tmp_path)
    for key in ("OPENAI_API_KEY", "GO2_DESKTOP_TOKEN", "LD_PRELOAD", "GO2_AES_KEY"):
        monkeypatch.setenv(key, "not-for-wirepod")
    env = services.environment("192.168.1.2")
    assert "not-for-wirepod" not in env.values()
    assert env["VECTOR_HOST_IP"] == "192.168.1.2"
    assert env["NO8084"] == "true"  # Only one 8084 TLS listener, no privileged 443.


def test_preparation_keeps_private_pairing_out_of_bundle_and_preserves_jdocs(tmp_path):
    services = service(tmp_path)
    for name in ("epod", "webroot", "intent-data"):
        (services.bundle / "assets" / name).mkdir(parents=True)
    (services.bundle / "dimensional.so").write_bytes(b"plugin")
    config = tmp_path / "pairing.ini"
    cert = tmp_path / "robot.cert"
    cert.write_text("private-cert")
    config.write_text(f"[abc123]\ncert={cert}\nguid=MTIzNDU2Nzg5MGFiY2RlZg==\nname=Vector-TEST\n")
    services.root.mkdir()
    (services.root / "apiConfig.json").write_text(' {"weather":{"enable":true,"provider":"saved"}}')
    (services.root / "jdocs").mkdir()
    jdocs = services.root / "jdocs/jdocs.json"
    jdocs.write_text('[{"thing":"vic:other","name":"vic.RobotSettings","jdoc":{"preserved":true}}]')
    t = {**target(), "sdk_config": str(config)}
    services.prepare(t)
    assert json.loads((services.root / "apiConfig.json").read_text())["weather"]["provider"] == "saved"
    assert json.loads(jdocs.read_text())[0]["jdoc"] == {"preserved": True}
    assert json.loads(jdocs.read_text())[1]["name"] == "vic.AppTokens"
    pairing = services.root / "jdocs/botSdkInfo.json"
    assert pairing.stat().st_mode & 0o777 == 0o600
    assert json.loads(pairing.read_text())["robots"][0]["guid"] == "MTIzNDU2Nzg5MGFiY2RlZg=="
    bridge = json.loads((services.root / "dimensional-voice.json").read_text())
    assert bridge["url"] == "http://127.0.0.1:8780"
    assert not list(services.bundle.rglob("*SdkInfo*"))


def test_native_audio_endpoint_token_scope_robot_and_session_guards(tmp_path, monkeypatch):
    app = create_app(Settings(root=tmp_path, desktop_token="desktop", env_file=tmp_path / "missing"))
    s, voice = app.state.supervisor, app.state.wirepod
    monkeypatch.setattr(s, "_launch", lambda: None)
    monkeypatch.setattr(app.state.vector_services, "start", lambda: None)
    transcribe = Mock(return_value="what time is it")
    monkeypatch.setattr("go2_setup.speech.Speech.transcribe", transcribe)
    voice.enable()
    h = {"Authorization": "Bearer " + voice.token, "X-Go2-Request": "1", "X-Vector-Serial": "abc123", "Content-Type": "audio/wav"}
    with TestClient(app) as client:
        assert client.get("/api/state", headers=h).status_code == 403
        assert client.post("/api/vector/wirepod/audio", headers=h, content=b"wav").status_code == 409
        s.target, s.connection, s.epoch = target(), "online", 7
        # Native commands can be transcribed with HumanCLI paused. No agent action is submitted.
        response = client.post("/api/vector/wirepod/audio", headers=h, content=b"wav")
        assert response.status_code == 200
        assert response.json() == {"text": "what time is it"}
        assert client.post("/api/vector/wirepod/audio", headers={**h, "X-Vector-Serial": "wrong"}, content=b"wav").status_code == 409
        assert client.post("/api/vector/wirepod/audio", headers=h, content=b"x" * (2*1024*1024+1)).status_code == 413
        def changed(*args):
            s.epoch += 1
            return "move forward"
        transcribe.side_effect = changed
        assert client.post("/api/vector/wirepod/audio", headers=h, content=b"wav").status_code == 409
        s.target, s.connection = None, "offline"


def test_auth_document_matches_existing_pairing_and_is_idempotent(tmp_path):
    path = tmp_path / "jdocs.json"
    token = base64.b64encode(b"0123456789abcdef").decode()
    preserve_app_tokens(path, "abc123", [token, token])
    original = path.read_bytes()
    entry = json.loads(original)[0]
    assert entry["thing"] == "vic:abc123"
    assert entry["jdoc"]["doc_version"] == 1
    hashes = json.loads(entry["jdoc"]["json_doc"])["client_tokens"]
    assert len(hashes) == 1
    value = base64.b64decode(hashes[0]["hash"])
    assert value[:32] == hashlib.sha256(base64.b64decode(token) + value[32:]).digest()
    assert token not in original.decode()
    assert path.stat().st_mode & 0o777 == 0o600
    preserve_app_tokens(path, "abc123", [token])
    assert path.read_bytes() == original
    refreshed = base64.b64encode(b"fedcba9876543210").decode()
    preserve_app_tokens(path, "abc123", [token, refreshed])
    updated = json.loads(path.read_text())[0]["jdoc"]
    assert updated["doc_version"] == 2
    assert len(json.loads(updated["json_doc"])["client_tokens"]) == 2


@pytest.mark.parametrize("contents", ['{"invalid":true}', 'broken', '[{"thing":"vic:abc123","name":"vic.AppTokens","jdoc":{}}]'])
def test_invalid_auth_document_is_never_replaced(tmp_path, contents):
    path = tmp_path / "jdocs.json"
    path.write_text(contents)
    with pytest.raises(ValueError, match="authorization document"):
        preserve_app_tokens(path, "abc123", [base64.b64encode(b"0123456789abcdef").decode()])
    assert path.read_text() == contents


def test_invalid_pairing_does_not_create_authorization(tmp_path):
    path = tmp_path / "jdocs.json"
    with pytest.raises(ValueError, match="pairing token"):
        preserve_app_tokens(path, "abc123", ["invalid-private-token"])
    assert not path.exists()
