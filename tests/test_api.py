from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
from go2_setup.api import create_app
from go2_setup.config import Settings
from go2_setup.catalog import Catalog
from go2_setup.records import inspect_recording


HEADERS = {"X-Go2-Request": "1"}


def settings(root):
    return Settings(root=root, env_file=root / "missing.env")


def make_recording(path):
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE _streams(name TEXT,config TEXT); INSERT INTO _streams VALUES('lidar','{}'); CREATE TABLE lidar(id INTEGER,ts REAL,pose_x REAL); CREATE TABLE lidar_blob(id INTEGER,data BLOB);"
        )
        db.executemany("INSERT INTO lidar VALUES(?,?,?)", [(1, 1, 0), (2, 2, 0), (3, 4, None)])
        db.executemany(
            "INSERT INTO lidar_blob VALUES(?,?)", [(1, b"a" * 30), (2, b"a" * 30), (3, b"a" * 30)]
        )


def test_origin_and_mutation_header_guard(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.post("/api/spaces", json={"name": "Casa"}).status_code == 403
        assert (
            client.post(
                "/api/spaces",
                json={"name": "Casa"},
                headers={**HEADERS, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/spaces", json={"name": "Casa"}, headers=HEADERS).status_code == 200


def test_import_is_a_copy_metrics_and_path_traversal(tmp_path):
    source = tmp_path / "source.db"
    make_recording(source)
    root = tmp_path / "spaces"
    with TestClient(create_app(settings(root))) as client:
        space = client.post("/api/spaces", json={"name": "Casa"}, headers=HEADERS).json()
        response = client.post(
            "/api/import", json={"space_id": space["id"], "path": str(source)}, headers=HEADERS
        )
        assert response.status_code == 200, response.text
        segment = response.json()
        assert Path(segment["path"]) != source
        assert inspect_recording(source)["streams"]["lidar"]["bytes"] == 90
        assert segment["stats"]["streams"]["lidar"]["poses"] == 2
        assert segment["stats"]["streams"]["lidar"]["gaps_over_1s"] == 1
        assert client.get("/api/files/../../etc/passwd/raw").status_code != 200
        assert client.get(f"/api/files/{segment['id']}/raw").status_code == 200
        assert (
            client.post("/api/mode", json={"mode": "explore"}, headers=HEADERS).status_code == 409
        )


def test_restart_recovers_catalog_without_resuming_motion(tmp_path):
    cfg = settings(tmp_path)
    cfg.initialize()
    catalog = Catalog(tmp_path)
    space = catalog.space("Casa")
    session = catalog.folder_item("session", space, status="recording")
    segment = catalog.folder_item("segment", session, status="recording")
    job = catalog.folder_item("map", segment, status="running")
    recovered = Catalog(tmp_path)
    assert recovered.get(session["id"])["status"] == "interrupted"
    assert recovered.get(segment["id"])["status"] == "interrupted"
    assert recovered.get(job["id"])["status"] == "interrupted"


def test_physical_disconnect_requires_observed_support_and_idle(tmp_path):
    from unittest.mock import Mock

    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        supervisor = app.state.supervisor
        supervisor.target = {"ip": "192.168.50.42", "replay": None}
        supervisor.next_retry = float("inf")
        supervisor.disconnect = Mock()
        supervisor.mode = "idle"
        assert client.post("/api/disconnect", headers=HEADERS).status_code == 409
        supervisor.disconnect.assert_not_called()
        supervisor.mode = "teleop"
        assert (
            client.post(
                "/api/disconnect", headers=HEADERS, json={"parked_confirmed": True}
            ).status_code
            == 409
        )
        supervisor.disconnect.assert_not_called()
        supervisor.mode = "idle"
        assert (
            client.post(
                "/api/disconnect", headers=HEADERS, json={"parked_confirmed": True}
            ).status_code
            == 200
        )
        supervisor.disconnect.assert_called_once()
        supervisor.target = None


def test_cloud_routes_keep_credentials_private_and_require_local_header(tmp_path):
    from unittest.mock import Mock

    app = create_app(settings(tmp_path))
    cloud = app.state.cloud
    cloud.begin_login = Mock(return_value={"login": {"code": "TEST-CODE"}})
    cloud.start = Mock(return_value={"status": "preparing", "percent": 0})
    with TestClient(app) as client:
        assert client.post("/api/cloud/login").status_code == 403
        assert client.post("/api/cloud/login", headers=HEADERS).status_code == 200
        cloud.begin_login.assert_called_once()
        assert client.post("/api/cloud/uploads/test", headers=HEADERS).json()["percent"] == 0
        cloud.start.assert_called_once_with("test")
        state = client.get("/api/state").json()
        assert "api_key" not in state["cloud"]
        assert "device_code" not in state["cloud"]


def test_teleop_api_accepts_dimos_default_and_boost_speeds(tmp_path):
    from unittest.mock import Mock

    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        supervisor = app.state.supervisor
        supervisor.connection = "online"
        supervisor.call = Mock(return_value={"ok": True})
        for speed in [0.5, -0.5, 1.0]:
            response = client.post(
                "/api/teleop", headers=HEADERS, json={"epoch": 1, "x": speed, "y": 0, "yaw": 0}
            )
            assert response.status_code == 200
            assert supervisor.call.call_args.args[1]["x"] == speed
        for invalid in ["NaN", "Infinity", "-Infinity"]:
            response = client.post(
                "/api/teleop", headers=HEADERS, json={"epoch": 1, "x": invalid, "y": 0, "yaw": 0}
            )
            assert response.status_code == 422
        supervisor.connection = "offline"
