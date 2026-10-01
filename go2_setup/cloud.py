"""Local dataset backups using the official DimOS Cloud multipart contract.

Credentials and presigned URLs never enter dashboard state. A stable SQLite backup
includes committed WAL data; raw recordings are never modified or removed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
import shutil
import sqlite3
import threading
import time
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests

from go2_setup.catalog import atomic_json
from go2_setup.records import inspect_recording

log = logging.getLogger(__name__)

API = "https://api.dimensional.org"
CONSOLE = "https://console.dimensional.org"
ACTIVE = {"preparing", "uploading", "verifying"}
PART_SIZE = 16 * 1024 * 1024
PART_ATTEMPTS = 6


class CloudError(ValueError):
    pass


class Paused(Exception):
    pass


def dataset_name(value):
    if not isinstance(value, str):
        raise CloudError("Enter a dataset name.")
    name = value.strip()
    if not name or len(name) > 120 or len(name.encode("utf-8")) > 200:
        raise CloudError("Use a dataset name between 1 and 120 characters (up to 200 UTF-8 bytes).")
    if name in {".", ".."} or any(ord(c) < 32 or c in '/\\<>:"|?*' for c in name):
        raise CloudError(
            "Use a dataset name without slashes, control characters or filename punctuation."
        )
    return name


def fingerprint(path):
    result = []
    for name in (str(path), str(path) + "-wal"):
        p = Path(name)
        if p.exists():
            s = p.stat()
            result.append([p.name, s.st_size, s.st_mtime_ns])
    return result


class CloudBackups:
    def __init__(self, settings, catalog):
        self.settings, self.catalog = settings, catalog
        self.credentials = settings.root / "cloud-credentials.json"
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.worker = None
        self.login_worker = None
        self.active = None
        self.account = None
        self.error = None
        self.login = None
        self.quota = None
        for segment in catalog.list("segment"):
            backup = segment.get("backup", {})
            if backup.get("status") in ACTIVE:
                self.save(segment["id"], status="paused", error="App restarted. Resume the upload.")

    def key(self):
        if key := os.environ.get("DIMOS_API_KEY"):
            return key
        try:
            return json.loads(self.credentials.read_text())["api_key"]
        except (OSError, ValueError, KeyError):
            return None

    def request(self, method, path, *, auth=True, **kwargs):
        headers = {}
        if auth:
            key = self.key()
            if not key:
                raise CloudError("Connect DimOS Cloud before uploading.")
            headers["Authorization"] = "Bearer " + key
        try:
            response = requests.request(
                method,
                API + path,
                headers=headers,
                timeout=(10, 45),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException:
            raise CloudError(
                "DimOS Cloud is unreachable. Check your connection and retry."
            ) from None
        if not 200 <= response.status_code < 300:
            message = {
                401: "Cloud sign-in expired or was revoked. Sign in again.",
                403: "This cloud account does not have access.",
                429: "Cloud quota or request limit reached. Check the cloud console.",
                413: "This dataset exceeds the cloud file-size limit.",
                404: "This cloud backup no longer exists or belongs to another account.",
            }
            raise CloudError(
                message.get(
                    response.status_code,
                    f"DimOS Cloud returned HTTP {response.status_code}. Retry the upload.",
                )
            )
        try:
            return response.json()
        except ValueError:
            raise CloudError("DimOS Cloud returned an invalid response.") from None

    def status(self):
        with self.lock:
            return dict(
                configured=bool(self.key()),
                account=self.account,
                login=self.login,
                error=self.error,
                quota=self.quota,
                active_segment=self.active,
                console_url=CONSOLE,
            )

    def refresh(self):
        who = self.request("GET", "/auth/whoami")
        quota = self.request("GET", "/v1/data/quota")
        # Reconcile local badges with remote truth, including remote deletion.
        uploads = self.request("GET", "/v1/data/uploads")["uploads"]
        remote = {u["id"]: u for u in uploads}
        for segment in self.catalog.list("segment"):
            with self.lock:
                try:
                    segment = self.catalog.get(segment["id"], "segment")
                except KeyError:
                    continue
                b = segment.get("backup", {})
                if b.get("status") != "complete":
                    continue
                if b.get("owner_id") != who["sub"]:
                    continue
                u = remote.get(b.get("upload_id"))
                if not u or u["state"] != "complete" or u["sha256"] != b.get("sha256"):
                    self.save(
                        segment["id"],
                        status="missing",
                        error="Cloud backup is no longer available.",
                    )
                elif fingerprint(segment["path"]) != b.get("source_fingerprint"):
                    self.save(
                        segment["id"],
                        status="changed",
                        error="Local recording changed. Upload a new backup.",
                    )
                else:
                    self.save(segment["id"], verified_at=time.time())
        with self.lock:
            self.account = {"email": who.get("email"), "id": who["sub"]}
            self.quota, self.error = quota, None
        return self.status()

    def begin_login(self):
        with self.lock:
            if self.active:
                raise CloudError("Pause the upload before changing cloud accounts.")
            if self.login_worker and self.login_worker.is_alive():
                return self.status()
            d = self.request("POST", "/auth/device", auth=False, params={"label": "DIMENSIONAL"})
            url = d.get("verification_uri_complete", d["verification_uri"])
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "console.dimensional.org":
                raise CloudError("Unexpected cloud sign-in address.")
            self.login = dict(
                url=url, code=d["user_code"], expires_at=time.time() + d["expires_in"]
            )
            self.error = None
            self.login_worker = threading.Thread(target=self._login, args=(d,), daemon=True)
            self.login_worker.start()
            return self.status()

    def sign_out(self):
        """Forget this device's DimOS Cloud key. Local recordings and backup badges stay."""
        with self.lock:
            if self.active:
                raise CloudError("Pause the upload before signing out.")
            if os.environ.get("DIMOS_API_KEY"):
                raise CloudError("This device is signed in through DIMOS_API_KEY. Remove it to sign out.")
            self.stop.set()
            self.credentials.unlink(missing_ok=True)
            self.account = self.quota = self.login = self.error = None
            self.stop = threading.Event()
            return self.status()

    def _login(self, device):
        interval = max(5, device["interval"])
        deadline = time.time() + device["expires_in"]
        try:
            while time.time() < deadline and not self.stop.wait(interval):
                r = self.request(
                    "POST", "/auth/token", auth=False, params={"device_code": device["device_code"]}
                )
                if r["status"] == "ok":
                    atomic_json(self.credentials, {"api_key": r["api_key"]})
                    self.credentials.chmod(0o600)
                    self.refresh()
                    return
                if r["status"] in {"denied", "expired"}:
                    raise CloudError("Cloud sign-in was denied or expired. Try again.")
                interval = max(interval, r.get("interval", interval))
            if not self.stop.is_set():
                raise CloudError("Cloud sign-in expired. Try again.")
        except CloudError as e:
            self.error = str(e)
        finally:
            with self.lock:
                self.login = None

    def save(self, ident, **changes):
        with self.lock:
            b = {**self.catalog.get(ident, "segment").get("backup", {}), **changes}
            self.catalog.update(ident, backup=b)
            return b

    def start(self, ident, name=None):
        with self.lock:
            if self.active:
                raise CloudError("Another dataset is uploading. Pause it or wait for completion.")
            if self.login_worker and self.login_worker.is_alive():
                raise CloudError("Finish cloud sign-in first.")
            if not self.key():
                raise CloudError("Connect DimOS Cloud before uploading.")
            segment = self.catalog.get(ident, "segment")
            if segment["status"] not in {"closed", "interrupted"}:
                raise CloudError("Save the recording before uploading.")
            if not Path(segment["path"]).is_file():
                raise CloudError("The recording file is missing.")
            old = segment.get("backup", {})
            saved_name = old.get("name") or (f"go2-{ident}" if old.get("upload_id") else None)
            chosen_name = dataset_name(name) if name is not None else saved_name
            if old.get("upload_id") and chosen_name != saved_name:
                raise CloudError(
                    "This upload already has a name. Resume it with its existing name."
                )
            if not chosen_name:
                stamp = datetime.fromtimestamp(segment["created"], timezone.utc).strftime(
                    "%Y-%m-%d %H-%M"
                )
                chosen_name = dataset_name(f"Go2 recording {stamp} {ident[:6]}")
            filename = old.get("filename") if old.get("upload_id") else None
            filename = filename or (
                chosen_name if chosen_name.lower().endswith(".db") else chosen_name + ".db"
            )
            self.active = ident
            self.pause.clear()
            b = self.save(
                ident,
                status="preparing",
                error=None,
                percent=0,
                name=chosen_name,
                filename=filename,
            )
            segment = {**segment, "backup": b}
            self.worker = threading.Thread(target=self._run, args=(segment,), daemon=True)
            self.worker.start()
            return b

    def pause_upload(self, ident):
        with self.lock:
            if self.active != ident:
                raise CloudError("This dataset is not uploading.")
            self.pause.set()
        return {"ok": True}

    def check(self):
        if self.pause.is_set() or self.stop.is_set():
            raise Paused()

    def snapshot(self, segment):
        source = Path(segment["path"])
        before = fingerprint(source)
        folder = self.settings.root / "cloud-staging"
        folder.mkdir(mode=0o700, exist_ok=True)
        target = folder / (segment["id"] + ".db")
        old = segment.get("backup", {})
        if target.exists() and old.get("source_fingerprint") == before and old.get("sha256"):
            return target, before
        size = sum(p[1] for p in before)
        if shutil.disk_usage(folder).free < size + 1024**3:
            raise CloudError("Not enough disk space to prepare a consistent dataset copy.")
        temp = target.with_suffix(".partial")
        temp.unlink(missing_ok=True)
        try:
            with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
                with sqlite3.connect(temp) as dst:
                    src.backup(dst, pages=1024, progress=lambda *args: self.check())
                    if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise CloudError(
                            "Recording integrity check failed. The original is untouched."
                        )
            if fingerprint(source) != before:
                raise CloudError("Recording changed during preparation. Save it and retry.")
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        return target, before

    @staticmethod
    def storage_url(url):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".amazonaws.com")
            or parsed.username
            or parsed.password
        ):
            raise CloudError("Unexpected cloud storage destination.")
        return url

    @staticmethod
    def storage_error(response):
        # S3 XML can contain credentials, signatures and canonical requests.
        # Surface only the bounded error code, never Message or the raw body.
        code = ""
        try:
            value = ET.fromstring(response.content[:65536]).findtext("Code", "")
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", value):
                code = " " + value
        except ET.ParseError:
            pass
        return f"Cloud storage returned HTTP {response.status_code}{code}. Resume to retry."

    def _put(self, url, data):
        self.storage_url(url)
        error = "Cloud storage is unreachable. Resume to retry missing parts."
        # Wi-Fi stalls are common on robots' networks: retry a part for about half a minute.
        for attempt in range(PART_ATTEMPTS):
            self.check()
            try:
                # Use the presigned request as issued. Adding Content-MD5 to a
                # host-only signature causes S3 to reject it as an unsigned header.
                # Verify the completed object's SHA-256 through a signed GET below.
                with requests.put(
                    url,
                    data=data,
                    timeout=(10, 90),
                    allow_redirects=False,
                ) as response:
                    if 200 <= response.status_code < 300:
                        if response.headers.get("ETag"):
                            return response.headers["ETag"]
                        raise CloudError("Cloud storage did not acknowledge the uploaded part.")
                    error = self.storage_error(response)
                    if response.status_code != 429 and response.status_code < 500:
                        raise CloudError(error)
            except requests.RequestException as exc:
                error = "Cloud storage connection failed. Resume to retry missing parts."
                # The exception text can contain the presigned URL and its signature.
                reason = re.sub(r"https?://\S+|url: \S+|X-Amz-\S+", "<redacted>", str(exc))[:300]
                log.warning("Cloud part upload attempt %d failed: %s: %s", attempt + 1, type(exc).__name__, reason)
            if attempt + 1 < PART_ATTEMPTS and self.stop.wait(min(2**attempt, 16)):
                self.check()
        raise CloudError(error)

    def _verify_download(self, url, expected_sha):
        self.storage_url(url)
        digest = hashlib.sha256()
        try:
            with requests.get(url, stream=True, timeout=(10, 90), allow_redirects=False) as r:
                if r.status_code != 200:
                    raise CloudError(self.storage_error(r))
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    self.check()
                    digest.update(chunk)
        except requests.RequestException:
            raise CloudError(
                "Cloud backup verification was interrupted. Resume to verify."
            ) from None
        if digest.hexdigest() != expected_sha:
            raise CloudError(
                "Downloaded backup checksum does not match the dataset. Backup is not verified."
            )

    def _run(self, segment):
        ident = segment["id"]
        try:
            who = self.request("GET", "/auth/whoami")
            with self.lock:
                self.account = {"email": who.get("email"), "id": who["sub"]}
            path, source_fp = self.snapshot(segment)
            digest = hashlib.sha256()
            with path.open("rb") as f:
                while chunk := f.read(1024 * 1024):
                    self.check()
                    digest.update(chunk)
            sha, size = digest.hexdigest(), path.stat().st_size
            stats = inspect_recording(path)
            session = self.catalog.get(segment["parent"], "session")
            manifest = dict(
                dataset_name=segment["backup"]["name"],
                streams=[dict(topic=name, **values) for name, values in stats["streams"].items()],
                segment_id=ident,
                session_id=session["id"],
                space_id=session["parent"],
                source=session.get("source"),
                dimos_sha=segment.get("dimos_sha"),
                recording_status=segment["status"],
                format="sqlite",
                duration=stats["duration"],
            )
            self.save(
                ident,
                sha256=sha,
                size=size,
                source_fingerprint=source_fp,
                owner_id=who["sub"],
                uploaded_bytes=0,
            )
            self.check()
            upload = self.request(
                "POST",
                "/v1/data/uploads",
                json=dict(
                    filename=segment["backup"]["filename"],
                    kind="recording",
                    size=size,
                    sha256=sha,
                    part_size=PART_SIZE,
                    robot_id=self.settings.serial,
                    manifest=manifest,
                ),
            )
            uid = upload["upload_id"]
            self.save(ident, upload_id=uid, status="uploading")
            self.quota = upload.get("quota")
            if upload["state"] != "complete":
                ps = upload["part_size"]
                if not 5 * 1024**2 <= ps <= 64 * 1024**2:
                    raise CloudError("Cloud requested an unsupported part size.")
                remote = self.request("GET", f"/v1/data/uploads/{uid}")
                if remote["state"] != "complete":
                    parts = {p["part_number"]: p["etag"] for p in remote["parts"]}
                    expected = (size + ps - 1) // ps
                    parts = {n: etag for n, etag in parts.items() if 1 <= n <= expected}
                    sent = sum(min(ps, size - (n - 1) * ps) for n in parts)
                    self.save(ident, uploaded_bytes=sent, percent=min(99, int(sent * 100 / size)))
                    urls = {p["part_number"]: p["url"] for p in upload["part_urls"]}
                    with path.open("rb") as f:
                        for n in range(1, expected + 1):
                            self.check()
                            if n in parts:
                                continue
                            f.seek((n - 1) * ps)
                            data = f.read(ps)
                            parts[n] = self._put(urls[n], data)
                            sent += len(data)
                            self.save(
                                ident, uploaded_bytes=sent, percent=min(99, int(sent * 100 / size))
                            )
                    self.check()
                    self.save(ident, status="verifying", percent=99)
                    self.request(
                        "POST",
                        f"/v1/data/uploads/{uid}/complete",
                        json={"parts": [dict(part_number=n, etag=parts[n]) for n in sorted(parts)]},
                    )
            self.save(ident, status="verifying", percent=99)
            remote = self.request("GET", f"/v1/data/uploads/{uid}")
            if remote["state"] != "complete":
                raise CloudError("Cloud has not confirmed completion. Resume to verify.")
            proof = self.request("GET", f"/v1/data/uploads/{uid}/download")
            if proof["sha256"] != sha:
                raise CloudError("Cloud checksum metadata does not match this dataset.")
            self._verify_download(proof["url"], sha)
            if proof.get("filename") and proof["filename"] != segment["backup"]["filename"]:
                self.save(
                    ident, name=proof["filename"].removesuffix(".db"), filename=proof["filename"]
                )
            if fingerprint(segment["path"]) != source_fp:
                raise CloudError(
                    "Local recording changed. Upload again to back up the current version."
                )
            self.save(
                ident,
                status="complete",
                percent=100,
                uploaded_bytes=size,
                verified_at=time.time(),
                error=None,
            )
            path.unlink(missing_ok=True)
            self.catalog.event("cloud", f"Dataset {ident[:6]} backed up to DimOS Cloud")
        except Paused:
            self.save(ident, status="paused", error=None)
        except CloudError as e:
            self.save(ident, status="failed", error=str(e))
        except Exception:
            # Never surface exceptions containing signed URLs, device codes or keys.
            self.save(
                ident,
                status="failed",
                error="Could not prepare or upload the dataset. The original is safe. Retry to resume.",
            )
        finally:
            with self.lock:
                self.active = None

    def close(self):
        self.stop.set()
        self.pause.set()
        for worker in (self.worker, self.login_worker):
            if worker:
                worker.join(timeout=2)
