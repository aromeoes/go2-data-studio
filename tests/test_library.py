from pathlib import Path
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from go2_setup.api import create_app
from go2_setup.config import Settings

HEADERS = {"X-Go2-Request": "1"}


@pytest.fixture
def library(tmp_path):
    app = create_app(Settings(root=tmp_path.resolve(), env_file=tmp_path / "missing.env"))
    cat = app.state.catalog
    space = cat.space("Original space")
    session = cat.folder_item("session", space, status="closed", source="import")
    segment = cat.folder_item("segment", session, status="closed")
    path = Path(segment["folder"]) / "raw.db"
    path.write_bytes(b"test recording")
    segment = cat.update(segment["id"], path=str(path))
    with TestClient(app) as client:
        yield app, client, space, session, segment
        app.state.supervisor.target = None
        app.state.supervisor.session = None
        app.state.cloud.active = None
        app.state.jobs.processes.clear()


def delete(client, segment, **kwargs):
    return client.post(
        f"/api/segments/{segment['id']}/delete", json={"confirmed": True}, headers=HEADERS, **kwargs
    )


def test_rename_preserves_ids_paths_children_and_manifest(library):
    app, client, space, session, segment = library
    route = f"/api/spaces/{space['id']}/rename"
    assert client.post(route, json={"name": "New"}).status_code == 403
    for invalid in ["   ", "x" * 81]:
        assert client.post(route, json={"name": invalid}, headers=HEADERS).status_code in {409, 422}
    renamed = client.post(route, json={"name": "  Office upstairs  "}, headers=HEADERS)
    assert renamed.status_code == 200
    assert renamed.json() == {**space, "name": "Office upstairs"}
    assert app.state.catalog.get(segment["id"]) == segment
    assert (
        json.loads((Path(space["folder"]) / "manifest.json").read_text())["name"]
        == "Office upstairs"
    )
    assert (
        client.post(
            f"/api/spaces/{segment['id']}/rename", json={"name": "Wrong"}, headers=HEADERS
        ).status_code
        == 409
    )


def test_delete_removes_raw_maps_and_staging_but_keeps_other_data(library):
    app, client, space, session, segment = library
    cat = app.state.catalog
    job = cat.folder_item("map", segment, status="ready")
    (Path(job["folder"]) / "map.pc2.lcm").write_bytes(b"map")
    sibling = cat.folder_item("segment", session, status="closed")
    original = cat.root / "imported-source.db"
    original.write_bytes(b"original")
    cat.update(session["id"], original_path=str(original))
    staging = cat.root / "cloud-staging"
    staging.mkdir()
    for suffix in ["db", "partial"]:
        (staging / f"{segment['id']}.{suffix}").write_bytes(b"staging")
    app.state.cloud.request = Mock(side_effect=AssertionError("No cloud deletion"))
    app.state.supervisor.call = Mock(side_effect=AssertionError("No robot commands"))
    response = delete(client, segment)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "removed_maps": 1, "warning": None}
    assert not Path(segment["folder"]).exists()
    assert not list(staging.iterdir())
    assert original.read_bytes() == b"original"
    assert Path(sibling["folder"]).is_dir()
    assert cat.get(space["id"]) == space
    for ident in [segment["id"], job["id"]]:
        with pytest.raises(KeyError):
            cat.get(ident)
    assert delete(client, segment).status_code == 404


@pytest.mark.parametrize(
    "busy",
    [
        "backup",
        "recording",
        "importing",
        "session",
        "upload",
        "verifying",
        "replay",
        "map",
        "cancelled_process",
    ],
)
def test_delete_refuses_protected_or_busy_segments(library, busy):
    app, client, space, session, segment = library
    cat = app.state.catalog
    if busy == "backup":
        cat.update(segment["id"], backup={"status": "complete"})
    elif busy in {"recording", "importing"}:
        cat.update(segment["id"], status=busy)
    elif busy == "session":
        app.state.supervisor.session = session
    elif busy == "upload":
        app.state.cloud.active = segment["id"]
    elif busy == "verifying":
        cat.update(segment["id"], backup={"status": "verifying"})
    elif busy == "replay":
        app.state.supervisor.target = {"replay": segment["path"]}
        app.state.supervisor.next_retry = float("inf")
    else:
        job = cat.folder_item("map", segment, status="running" if busy == "map" else "cancelled")
        if busy == "cancelled_process":
            app.state.jobs.processes[job["id"]] = Mock()
    assert delete(client, segment).status_code == 409
    assert Path(segment["path"]).read_bytes() == b"test recording"
    assert cat.get(segment["id"])
    app.state.supervisor.session = None
    app.state.supervisor.target = None
    app.state.jobs.processes.clear()


def test_delete_requires_local_header_and_explicit_confirmation(library):
    app, client, space, session, segment = library
    route = f"/api/segments/{segment['id']}/delete"
    assert client.post(route, json={"confirmed": True}).status_code == 403
    assert client.post(route, json={}, headers=HEADERS).status_code == 409
    assert Path(segment["path"]).exists()


def test_delete_rejects_symlinked_segment(library):
    app, client, space, session, segment = library
    folder = Path(segment["folder"])
    elsewhere = app.state.catalog.root / "unrelated"
    folder.rename(elsewhere)
    folder.symlink_to(elsewhere, target_is_directory=True)
    assert delete(client, segment).status_code == 409
    assert (elsewhere / "raw.db").exists()


def test_delete_reports_disk_cleanup_failure(library, monkeypatch):
    app, client, space, session, segment = library
    monkeypatch.setattr("go2_setup.library.shutil.rmtree", Mock(side_effect=OSError("busy")))
    response = delete(client, segment)
    assert response.status_code == 200
    assert "some files remain" in response.json()["warning"]
    assert app.state.catalog.list("segment") == []
    assert list((app.state.catalog.root / ".deleting").glob("*/**/raw.db"))
