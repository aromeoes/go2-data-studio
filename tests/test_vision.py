import json
import stat
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from go2_setup.vision import Vision
from go2_setup.api import create_app
from go2_setup.config import Settings

KEY = "sk-test-only-not-a-real-key-12345"


def test_key_is_private_persistent_and_never_returned(tmp_path):
    with TestClient(
        create_app(Settings(root=tmp_path, env_file=tmp_path / "missing.env"))
    ) as client:
        r = client.post(
            "/api/agent/vision",
            headers={"X-Go2-Request": "1"},
            json={"api_key": KEY, "enabled": True},
        )
        assert r.status_code == 200
        assert KEY not in r.text
        assert KEY not in client.get("/api/state").text
        assert stat.S_IMODE((tmp_path / "vision.json").stat().st_mode) == 0o600
        assert Vision(tmp_path).status()["enabled"]
        assert client.post("/api/agent/vision", json={"api_key": KEY}).status_code == 403


def test_vision_sends_only_requested_frame_and_question(monkeypatch, tmp_path):
    vision = Vision(tmp_path)
    post = Mock(
        return_value=Mock(
            ok=True,
            json=lambda: {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Veo una puerta."}],
                    }
                ]
            },
        )
    )
    monkeypatch.setattr("go2_setup.vision.requests.post", post)
    with pytest.raises(ValueError, match="API key"):
        vision.describe("qué ves", "test-jpeg")
    post.assert_not_called()
    vision.configure(KEY, True)
    assert vision.describe("qué ves", "test-jpeg") == "Veo una puerta."
    args = post.call_args
    assert args.args[0] == "https://api.openai.com/v1/responses"
    body = args.kwargs["json"]
    assert body["store"] is False
    assert body["input"][0]["content"][1]["image_url"] == "data:image/jpeg;base64,test-jpeg"
    assert "tools" not in body
    assert KEY not in json.dumps(body)
    vision.configure("", False)
    with pytest.raises(ValueError):
        vision.describe("qué ves", "test-jpeg")
    assert post.call_count == 1


def test_provider_errors_are_redacted(monkeypatch, tmp_path):
    vision = Vision(tmp_path)
    vision.configure(KEY, True)
    monkeypatch.setattr(
        "go2_setup.vision.requests.post",
        Mock(return_value=Mock(ok=False, status_code=401, text=KEY)),
    )
    with pytest.raises(ValueError, match="Invalid") as error:
        vision.describe("qué ves", "image")
    assert KEY not in str(error.value)
