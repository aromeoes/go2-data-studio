import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from go2_setup.catalog import Catalog, atomic_json
from go2_setup.cloud import CloudBackups, CloudError, dataset_name, fingerprint
from go2_setup.config import Settings


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("DIMOS_API_KEY", raising=False)
    settings = Settings(root=tmp_path)
    settings.initialize()
    catalog = Catalog(tmp_path)
    space = catalog.space("Office")
    session = catalog.folder_item("session", space, status="closed", source="robot")
    segment = catalog.folder_item("segment", session, status="interrupted")
    path = Path(segment["folder"]) / "raw.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE _streams(name TEXT,config TEXT); INSERT INTO _streams VALUES('lidar','{}'); CREATE TABLE lidar(id INTEGER,ts REAL,pose_x REAL); CREATE TABLE lidar_blob(id INTEGER,data BLOB);"
        )
        db.execute("INSERT INTO lidar VALUES(1,1,0)")
        db.execute("INSERT INTO lidar_blob VALUES(1,?)", (b"x" * (11 * 1024**2),))
    segment = catalog.update(segment["id"], path=str(path))
    cloud = CloudBackups(settings, catalog)
    atomic_json(cloud.credentials, {"api_key": "dimos_sk_test_secret"})
    cloud._verify_download = Mock()  # Multipart fake; signed downloads are tested separately.
    yield cloud, catalog, segment
    cloud.close()


class Remote:
    def __init__(self, cloud):
        self.cloud = cloud
        self.parts = {}
        self.upload = None
        self.state = "pending"
        self.fail_part = None
        self.sent = []
        self.corrupt = False
        self.missing = False

    def request(self, method, path, **kwargs):
        if path == "/auth/whoami":
            return {"sub": "owner", "email": "test@example.org"}
        if path == "/v1/data/quota":
            return {"used_total": 0, "pct": 0}
        if path == "/v1/data/uploads" and method == "GET":
            return {
                "uploads": []
                if self.missing
                else [{"id": "upload", "state": self.state, "sha256": self.upload["sha256"]}]
            }
        if path == "/v1/data/uploads" and method == "POST":
            body = kwargs["json"]
            if self.upload:
                assert body["sha256"] == self.upload["sha256"]
            self.upload = body
            return {
                "state": self.state,
                "upload_id": "upload",
                "part_size": 5 * 1024**2,
                "part_urls": [{"part_number": i, "url": str(i)} for i in (1, 2, 3)],
            }
        if path.endswith("/complete"):
            assert [p["part_number"] for p in kwargs["json"]["parts"]] == [1, 2, 3]
            data = b"".join(self.parts[i] for i in (1, 2, 3))
            assert len(data) == self.upload["size"]
            assert hashlib.sha256(data).hexdigest() == self.upload["sha256"]
            self.state = "complete"
            return {"state": "complete"}
        if path.endswith("/download"):
            return {
                "sha256": "incorrect" if self.corrupt else self.upload["sha256"],
                "url": "https://bucket.s3.amazonaws.com/object",
            }
        return {
            "state": self.state,
            "parts": [{"part_number": n, "etag": str(n)} for n in self.parts],
        }

    def put(self, url, data):
        n = int(url)
        self.sent.append(n)
        assert self.cloud.catalog.get(self.cloud.active)["backup"]["percent"] < 100
        if n == self.fail_part:
            raise CloudError("Network interrupted")
        self.parts[n] = data
        return str(n)


def run(cloud, segment):
    cloud.start(segment["id"])
    cloud.worker.join(10)
    assert not cloud.worker.is_alive()
    return cloud.catalog.get(segment["id"])["backup"]


def test_multipart_resume_and_only_mark_complete_after_verification(setup):
    cloud, catalog, segment = setup
    remote = Remote(cloud)
    cloud.request, cloud._put = remote.request, remote.put
    before = fingerprint(segment["path"])
    remote.fail_part = 2
    backup = run(cloud, segment)
    assert backup["status"] == "failed"
    assert 0 < backup["percent"] < 100
    assert remote.sent == [1, 2]
    remote.fail_part = None
    backup = run(cloud, segment)
    assert remote.sent == [1, 2, 2, 3]
    assert backup["status"] == "complete"
    assert backup["percent"] == 100
    assert backup["sha256"] == remote.upload["sha256"]
    cloud._verify_download.assert_called_with(
        "https://bucket.s3.amazonaws.com/object", backup["sha256"]
    )
    assert remote.upload["manifest"]["streams"][0]["topic"] == "lidar"
    assert fingerprint(segment["path"]) == before
    assert not (cloud.settings.root / "cloud-staging" / (segment["id"] + ".db")).exists()
    # Another attempt is deduplicated by the remote service, with no bytes resent.
    assert run(cloud, segment)["status"] == "complete"
    assert remote.sent == [1, 2, 2, 3]
    # A remote deletion removes the backed-up badge on reconciliation.
    remote.missing = True
    cloud.refresh()
    assert catalog.get(segment["id"])["backup"]["status"] == "missing"


def test_checksum_mismatch_never_claims_backed_up(setup):
    cloud, _, segment = setup
    remote = Remote(cloud)
    remote.corrupt = True
    cloud.request, cloud._put = remote.request, remote.put
    b = run(cloud, segment)
    assert b["status"] == "failed"
    assert b["percent"] == 99
    assert "checksum" in b["error"]


def test_snapshot_includes_committed_wal_without_modifying_original(setup):
    cloud, _, segment = setup
    db = sqlite3.connect(segment["path"])
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("INSERT INTO lidar VALUES(2,2,0)")
    db.commit()
    before = fingerprint(segment["path"])
    path, _ = cloud.snapshot(segment)
    with sqlite3.connect(path) as backup:
        assert backup.execute("SELECT count(*) FROM lidar").fetchone()[0] == 2
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert fingerprint(segment["path"]) == before
    db.close()


def test_recording_guard_and_recovery(setup):
    cloud, catalog, segment = setup
    catalog.update(segment["id"], status="recording")
    with pytest.raises(CloudError, match="Save"):
        cloud.start(segment["id"])
    catalog.update(
        segment["id"],
        status="closed",
        backup={"status": "uploading", "percent": 42, "upload_id": "existing"},
    )
    recovered = CloudBackups(cloud.settings, catalog)
    b = catalog.get(segment["id"])["backup"]
    assert b["status"] == "paused" and b["percent"] == 42
    assert b["upload_id"] == "existing"
    assert recovered.active is None
    recovered.close()
    assert "dimos_sk_test_secret" not in str(cloud.status())


def test_signed_put_preserves_host_only_signature_without_extra_auth_headers(setup, monkeypatch):
    cloud, _, _ = setup
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = 200
    response.headers = {"ETag": "etag"}
    put = Mock(return_value=response)
    monkeypatch.setattr("go2_setup.cloud.requests.put", put)
    assert (
        cloud._put("https://bucket.s3.us-east-1.amazonaws.com/object?signature=secret", b"part")
        == "etag"
    )
    headers = put.call_args.kwargs.get("headers", {})
    assert "Authorization" not in headers
    assert "Content-MD5" not in headers
    assert put.call_args.kwargs["allow_redirects"] is False
    with pytest.raises(CloudError, match="destination"):
        cloud._put("http://127.0.0.1/private", b"part")


def test_pause_retains_remote_parts_and_can_resume(setup):
    cloud, _, segment = setup
    remote = Remote(cloud)
    cloud.request = remote.request

    def put(url, data):
        result = remote.put(url, data)
        cloud.pause_upload(segment["id"])
        return result

    cloud._put = put
    assert run(cloud, segment)["status"] == "paused"
    assert remote.sent == [1]
    cloud._put = remote.put
    assert run(cloud, segment)["status"] == "complete"
    assert remote.sent == [1, 2, 3]


def test_device_login_persists_private_key_and_exposes_only_public_code(setup):
    cloud, _, _ = setup
    cloud.credentials.unlink()
    cloud.stop.wait = lambda seconds: False

    def request(method, path, **kwargs):
        if path == "/auth/device":
            return {
                "device_code": "private-device-secret",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://console.dimensional.org/activate",
                "verification_uri_complete": "https://console.dimensional.org/activate?code=ABCD-EFGH",
                "expires_in": 300,
                "interval": 5,
            }
        assert kwargs["params"]["device_code"] == "private-device-secret"
        return {"status": "ok", "api_key": "dimos_sk_new_secret"}

    cloud.request = request
    cloud.refresh = lambda: {}
    cloud.begin_login()
    cloud.login_worker.join(2)
    assert cloud.key() == "dimos_sk_new_secret"
    assert cloud.credentials.stat().st_mode & 0o777 == 0o600
    assert cloud.status()["login"] is None
    assert "private-device-secret" not in str(cloud.status())
    assert "dimos_sk_new_secret" not in str(cloud.status())


def test_cloud_http_errors_never_expose_response_body_or_signed_url(setup, monkeypatch):
    cloud, _, _ = setup
    response = Mock(status_code=401, text="secret signed URL and bearer key")
    monkeypatch.setattr("go2_setup.cloud.requests.request", Mock(return_value=response))
    with pytest.raises(CloudError, match="Sign in again") as error:
        cloud.request("GET", "/auth/whoami")
    assert "secret" not in str(error.value)


def storage_response(status=200, content=b"", chunks=()):
    response = Mock(status_code=status, content=content)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = iter(chunks)
    return response


def test_s3_permanent_rejection_is_not_retried_and_is_redacted(setup, monkeypatch):
    cloud, _, _ = setup
    r = storage_response(
        403,
        b"<Error><Code>AccessDenied</Code><Message>signature-secret</Message><CanonicalRequest>private-token</CanonicalRequest></Error>",
    )
    put = Mock(return_value=r)
    monkeypatch.setattr("go2_setup.cloud.requests.put", put)
    with pytest.raises(CloudError, match="403 AccessDenied") as error:
        cloud._put("https://bucket.s3.amazonaws.com/object?secret", b"part")
    assert "secret" not in str(error.value) and "private-token" not in str(error.value)
    put.assert_called_once()


def test_streamed_download_verifies_actual_bytes_and_rejects_corruption(setup, monkeypatch):
    cloud, _, _ = setup
    expected = hashlib.sha256(b"firstsecond").hexdigest()
    get = Mock(return_value=storage_response(chunks=[b"first", b"second"]))
    monkeypatch.setattr("go2_setup.cloud.requests.get", get)
    CloudBackups._verify_download(cloud, "https://bucket.s3.amazonaws.com/object", expected)
    assert get.call_args.kwargs["stream"] is True
    assert "Authorization" not in get.call_args.kwargs.get("headers", {})
    get.return_value = storage_response(chunks=[b"corrupted"])
    with pytest.raises(CloudError, match="checksum"):
        CloudBackups._verify_download(cloud, "https://bucket.s3.amazonaws.com/object", expected)


def test_unverified_remote_bytes_never_reach_complete(setup):
    cloud, _, segment = setup
    remote = Remote(cloud)
    cloud.request, cloud._put = remote.request, remote.put
    cloud._verify_download.side_effect = CloudError("Downloaded backup checksum does not match")
    b = run(cloud, segment)
    assert remote.state == "complete"
    assert b["status"] == "failed" and b["percent"] == 99
    cloud._verify_download.side_effect = None
    assert run(cloud, segment)["status"] == "complete"
    assert remote.sent == [1, 2, 3]


def test_named_upload_keeps_name_on_resume_and_preserves_local_file(setup):
    cloud, catalog, segment = setup
    remote = Remote(cloud)
    cloud.request, cloud._put = remote.request, remote.put
    remote.fail_part = 2
    before = fingerprint(segment["path"])
    cloud.start(segment["id"], name="  Office west wing  ")
    cloud.worker.join(10)
    assert not cloud.worker.is_alive()
    assert remote.upload["filename"] == "Office west wing.db"
    assert remote.upload["manifest"]["dataset_name"] == "Office west wing"
    assert catalog.get(segment["id"])["backup"]["name"] == "Office west wing"
    with pytest.raises(CloudError, match="existing name"):
        cloud.start(segment["id"], name="Different name")
    remote.fail_part = None
    backup = run(cloud, segment)
    assert backup["status"] == "complete"
    assert backup["name"] == "Office west wing"
    assert remote.upload["filename"] == "Office west wing.db"
    assert fingerprint(segment["path"]) == before


@pytest.mark.parametrize(
    "name", ["", "  ", "../office", "room\\file", "a" * 121, "x\nroom", "..", "🌏" * 60]
)
def test_invalid_dataset_names(name):
    with pytest.raises(CloudError):
        dataset_name(name)


def test_legacy_upload_resumes_with_original_filename(setup):
    cloud, catalog, segment = setup
    catalog.update(segment["id"], backup={"status": "paused", "upload_id": "upload"})
    remote = Remote(cloud)
    cloud.request, cloud._put = remote.request, remote.put
    assert run(cloud, segment)["status"] == "complete"
    assert remote.upload["filename"] == f"go2-{segment['id']}.db"


def test_deduplicated_upload_displays_actual_cloud_name(setup):
    cloud, catalog, segment = setup
    remote = Remote(cloud)

    def request(method, path, **kwargs):
        result = remote.request(method, path, **kwargs)
        if path.endswith("/download"):
            result["filename"] = "Previously backed up.db"
        return result

    cloud.request, cloud._put = request, remote.put
    cloud.start(segment["id"], name="New label")
    cloud.worker.join(10)
    backup = catalog.get(segment["id"])["backup"]
    assert backup["status"] == "complete"
    assert backup["name"] == "Previously backed up"
    assert backup["filename"] == "Previously backed up.db"
