from unittest.mock import Mock

from fastapi.testclient import TestClient

from go2_setup.api import create_app
from go2_setup.config import Settings
from go2_setup.platform_files import reveal_file


def test_desktop_identity_and_shutdown_are_private(tmp_path):
    cfg = Settings(root=tmp_path, env_file=tmp_path / "none", desktop_token="test-session")
    app = create_app(cfg)
    headers = {"X-Go2-Request": "1", "X-Go2-Desktop": "test-session"}
    with TestClient(app) as client:
        assert client.get("/api/state").status_code == 403
        assert client.get("/api/desktop/status").status_code == 403
        assert client.get("/api/desktop/status", headers=headers).json()["pid"] > 0
        supervisor = app.state.supervisor
        supervisor.next_retry = float("inf")
        supervisor.target = {"ip": "192.168.50.42", "replay": None}
        supervisor.disconnect = Mock()
        assert client.post("/api/desktop/prepare-quit", headers=headers).status_code == 409
        supervisor.disconnect.assert_not_called()
        supervisor.target = None
        assert client.post("/api/desktop/prepare-quit", headers=headers).status_code == 200
        assert (
            client.post("/api/connect", json={"ip": "192.168.50.42"}, headers=headers).status_code
            == 409
        )
        assert supervisor.target is None


def test_desktop_routes_are_disabled_for_browser_only_server(tmp_path):
    with TestClient(create_app(Settings(root=tmp_path, env_file=tmp_path / "none"))) as client:
        assert client.get("/api/desktop/status").status_code == 403


def test_reveal_uses_platform_file_manager(tmp_path, monkeypatch):
    import go2_setup.platform_files as files

    run = Mock()
    monkeypatch.setattr(files.subprocess, "run", run)
    monkeypatch.setattr(files.sys, "platform", "linux")
    reveal_file(tmp_path / "map.rrd")
    assert run.call_args.args[0] == ["xdg-open", str(tmp_path)]
    monkeypatch.setattr(files.sys, "platform", "darwin")
    reveal_file(tmp_path / "map.rrd")
    assert run.call_args.args[0] == ["open", "-R", str(tmp_path / "map.rrd")]
