from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from go2_setup.api import create_app
from go2_setup.config import Settings
from go2_setup.speech import Speech, MAX_AUDIO_BYTES


def configured(**overrides):
    return Mock(resolve=lambda: dict(provider="openai", base_url="", api_key="private-key", **overrides))


def test_transcription_uses_official_endpoint_and_returns_only_text(monkeypatch):
    post = Mock(return_value=Mock(ok=True, json=lambda: {"text": "  what do you see?  "}))
    monkeypatch.setattr("go2_setup.speech.requests.post", post)
    assert Speech(configured()).transcribe(b"audio", "audio/webm") == "what do you see?"
    args, kw = post.call_args
    assert args == ("https://api.openai.com/v1/audio/transcriptions",)
    assert kw["allow_redirects"] is False
    assert kw["files"]["file"][1] == b"audio"


@pytest.mark.parametrize("cfg", [
    {"provider": "anthropic", "base_url": "", "api_key": "secret"},
    {"provider": "openai", "base_url": "https://other.example", "api_key": "secret"},
    {"provider": "openai", "base_url": "", "api_key": ""},
])
def test_no_cross_provider_key_reuse(monkeypatch, cfg):
    post = Mock()
    monkeypatch.setattr("go2_setup.speech.requests.post", post)
    with pytest.raises(ValueError, match="OpenAI key"):
        Speech(Mock(resolve=lambda: cfg)).transcribe(b"audio", "audio/webm")
    post.assert_not_called()


def test_errors_never_echo_provider_body_and_lock_is_released(monkeypatch):
    response = Mock(ok=False, status_code=401, text="private-key")
    monkeypatch.setattr("go2_setup.speech.requests.post", Mock(return_value=response))
    speech = Speech(configured())
    with pytest.raises(ValueError, match="rejected") as error:
        speech.transcribe(b"audio", "audio/webm")
    assert "private-key" not in str(error.value)
    assert not speech.lock.locked()


def test_endpoint_size_origin_and_stale_control(monkeypatch, tmp_path):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    monkeypatch.setattr(app.state.supervisor, "close", lambda: app.state.supervisor.done.set())
    s = app.state.supervisor
    s.connection, s.mode, s.epoch = "online", "agent", 4
    transcribe = Mock(return_value="status")
    monkeypatch.setattr(Speech, "transcribe", transcribe)
    headers = {"X-Go2-Request": "1", "Content-Type": "audio/webm"}
    with TestClient(app) as client:
        url = "/api/agent/transcribe?epoch=4"
        assert client.post(url, content=b"audio").status_code == 403
        assert client.post(url, content=b"audio", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        assert client.post(url, content=b"a" * (MAX_AUDIO_BYTES + 1), headers=headers).status_code == 413
        assert client.post(url, content=b"audio", headers={**headers,"Content-Type":"text/plain"}).status_code == 415
        assert client.post(url, content=b"audio", headers=headers).json() == {"text":"status"}
        assert not app.state.agent.messages  # Transcription never executes a tool.
        def changed(*args):
            s.epoch += 1
            return "walk forward"
        transcribe.side_effect = changed
        assert client.post(url, content=b"audio", headers=headers).status_code == 409
        transcribe.reset_mock()
        assert client.post(url, content=b"audio", headers=headers).status_code == 409
        transcribe.assert_not_called()
