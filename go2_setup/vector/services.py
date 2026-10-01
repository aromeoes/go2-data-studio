"""Session-scoped local wire-pod. This never connects an SDK or acquires motion control."""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import threading
import time

from go2_setup.vector.credentials import load_credentials

WIREPOD_SHA = "347c45f7a4dba9adba7fa003c08248d301f19393"


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(value, stream)
    os.chmod(temp, 0o600)
    temp.replace(path)


def preserve_app_tokens(path, serial, tokens):
    """Seed wire-pod's authorization document using the existing private pairing.

    botSdkInfo alone is insufficient: upstream falls back to a global token when
    vic.AppTokens is missing. Keep all other documents and existing app tokens.
    """
    try:
        raw_tokens = [base64.b64decode(token, validate=True) for token in dict.fromkeys(tokens)]
        if any(len(token) != 16 for token in raw_tokens):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Vector pairing token is invalid. Import its existing wire-pod SDK pairing again.") from None
    try:
        docs = json.loads(path.read_text()) if path.exists() else []
        if not isinstance(docs, list) or any(not isinstance(doc, dict) for doc in docs):
            raise ValueError()
        entry = next((d for d in docs if d.get("thing") == "vic:" + serial and d.get("name") == "vic.AppTokens"), None)
        if entry is None:
            entry = {"thing": "vic:" + serial, "name": "vic.AppTokens", "jdoc": {
                "doc_version": 0, "fmt_version": 1, "client_metadata": "data-studio-pairing", "json_doc": '{"client_tokens":[]}',
            }}
            docs.append(entry)
        jdoc = entry["jdoc"]
        body = json.loads(jdoc["json_doc"])
        existing = body["client_tokens"]
        if not isinstance(existing, list):
            raise ValueError()
        hashes = [base64.b64decode(t["hash"], validate=True) for t in existing]
        if any(len(h) != 48 for h in hashes):
            raise ValueError()
        changed = False
        for token in raw_tokens:
            if any(hmac.compare_digest(hashlib.sha256(token + h[32:]).digest(), h[:32]) for h in hashes):
                continue
            salt = os.urandom(16)
            hashed = hashlib.sha256(token + salt).digest() + salt
            existing.append({"hash": base64.b64encode(hashed).decode(), "client_name": "Go2 Data Studio",
                             "app_id": "SDK", "issued_at": datetime.now(timezone.utc).isoformat()})
            hashes.append(hashed)
            changed = True
        if changed:
            jdoc["doc_version"] = int(jdoc.get("doc_version", 0)) + 1
            jdoc["json_doc"] = json.dumps(body)
            private_json(path, docs)
        else:
            path.chmod(0o600)
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Vector's local authorization document is invalid. Restore the wire-pod pairing backup before connecting.") from None


def host_address(robot_ip):
    address = ipaddress.ip_address(robot_ip)
    if not address.is_private or address.is_loopback or address.version != 4:
        raise ValueError("Vector requires a private IPv4 address on this computer's LAN")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # UDP connect selects the route without sending a packet to the robot.
        sock.connect((str(address), 443))
        host = sock.getsockname()[0]
    if host.startswith("127."):
        raise ValueError("Vector's LAN is unavailable")
    return host


class VectorServices:
    def __init__(self, settings, supervisor, voice, speech_config, bundle=None):
        self.settings, self.supervisor, self.voice = settings, supervisor, voice
        self.speech_config = speech_config
        self.bundle = Path(bundle or os.environ.get("VECTOR_WIREPOD_RUNTIME", settings.runtime / "wirepod"))
        self.root = settings.root / "wirepod"
        self.stop_event = threading.Event()
        self.thread = None
        self.child = None
        self.log = None
        self.active = None
        self.retry_at = 0
        self.started = 0
        self.plugin_ready = False
        self.server_ready = False
        self.lock = threading.RLock()
        self.info = {"state": "stopped", "message": "Starts when you connect to Vector", "host": None}

    def status(self):
        with self.lock:
            return dict(self.info)

    def report(self, state, message, **extra):
        with self.lock:
            self.info = {**self.info, "state": state, "message": message, **extra}

    def voice_result(self, error=None):
        with self.lock:
            self.info["voice_error"] = error

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="vector-services")
            self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                with self.supervisor.lock:
                    target = dict(self.supervisor.target) if self.supervisor.target else None
                self.reconcile(target)
            except ValueError as error:
                self.stop_child()
                self.report("configuration_error", str(error))
                self.retry_at = time.monotonic() + 15
            except Exception:
                # Credential contents and arbitrary SDK exception strings must not reach UI/logs.
                self.stop_child()
                self.report("error", "Local Vector services failed. Check the wire-pod log.")
                self.retry_at = time.monotonic() + 15
            self.stop_event.wait(0.5)
        self.stop_child()
        self.report("stopped", "Vector services stopped", host=None)

    def validate_bundle(self):
        info = json.loads((self.bundle / "runtime.json").read_text())
        arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64"}.get(platform.machine())
        if (info.get("format"), info.get("sha"), info.get("platform"), info.get("arch")) != (
            1, WIREPOD_SHA, {"Darwin": "darwin", "Linux": "linux"}.get(platform.system()), arch
        ):
            raise ValueError("Install the wire-pod bundle built for this computer")
        for name in ("wirepod", "dimensional.so"):
            if hashlib.sha256((self.bundle / name).read_bytes()).hexdigest() != info.get("sha256", {}).get(name):
                raise ValueError("The wire-pod runtime failed its integrity check. Reinstall the application.")

    def prepare(self, target):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        # Only public, versioned assets are bundled. Robot pairing and jdocs remain private.
        for name in ("epod", "intent-data", "webroot"):
            destination = self.root / name
            if destination.is_symlink():
                destination.unlink()
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(self.bundle / "assets" / name, destination)
        (self.root / "plugins").mkdir(exist_ok=True, mode=0o700)
        shutil.copy2(self.bundle / "dimensional.so", self.root / "plugins" / "dimensional.so")
        for directory in ("jdocs", "session-certs"):
            (self.root / directory).mkdir(exist_ok=True, mode=0o700)
        pairing = load_credentials(target["sdk_config"], target["serial"])
        serial = target["serial"]
        if not serial or any(c not in "0123456789abcdefABCDEF" for c in serial):
            raise ValueError("Invalid Vector serial")
        cert = Path(pairing["cert"])
        destination = self.root / "session-certs" / serial
        shutil.copyfile(cert, destination)
        destination.chmod(0o600)
        # Preserve other saved robots and jdocs. Never activate/reset the robot here.
        bots_path = self.root / "jdocs" / "botSdkInfo.json"
        bots = json.loads(bots_path.read_text()) if bots_path.exists() else {"robots": []}
        bots.setdefault("global_guid", pairing["guid"])
        saved = next((r for r in bots["robots"] if r["esn"] == serial), None)
        if saved is None:
            saved = {"esn": serial}
            bots["robots"].append(saved)
        # A native token refresh may have updated this GUID. Do not undo it using
        # a stale SDK INI; authorize both the saved SDK and wire-pod pairing.
        saved.setdefault("guid", pairing["guid"])
        preserve_app_tokens(self.root / "jdocs" / "jdocs.json", serial, [pairing["guid"], saved["guid"]])
        saved.update(ip_address=target["ip"] + ":443", activated=True)
        private_json(bots_path, bots)
        config_path = self.root / "apiConfig.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        config.update({
            "STT": {"provider": "whisper", "language": config.get("STT", {}).get("language", "en-US")},
            "server": {"epconfig": True, "port": "8084"},
            "hasreadfromenv": True, "pastinitialsetup": True,
        })
        config.setdefault("knowledge", {"enable": False})
        config.setdefault("weather", {"enable": False})
        private_json(config_path, config)
        self.voice.enable()
        private_json(self.root / "dimensional-voice.json", {
            "url": f"http://127.0.0.1:{self.settings.port}", "token_file": str(self.voice.path),
        })
        (self.root / "version").write_text(WIREPOD_SHA)

    def environment(self, host):
        # Do not pass application/cloud/LLM credentials to the child process.
        env = {key: value for key, value in os.environ.items() if key in {"HOME", "USER", "TMPDIR", "LANG"}}
        env.update(PATH="/usr/bin:/bin", VECTOR_HOST_IP=host,
                   STT_SERVICE="whisper", STT_LANGUAGE="en-US", DISABLE_MDNS="true",
                   NO8084="true", JDOCS_PINGER_ENABLED="false", DEBUG_LOGGING="false",
                   WEBSERVER_PORT="18084", DIMENSIONAL_VOICE_CONFIG=str(self.root / "dimensional-voice.json"))
        return env

    def reconcile(self, target):
        wanted = target and target.get("kind") == "vector" and not target.get("replay") and not self.settings.replay_only
        identity = (target.get("serial"), target.get("ip"), target.get("sdk_config")) if wanted else None
        if identity != self.active:
            self.stop_child()
            self.active, self.retry_at = identity, 0
        if not wanted:
            self.report("stopped", "Starts when you connect to Vector", host=None)
            return
        if self.child is not None:
            if self.child.poll() is not None:
                self.stop_child()
                self.retry_at = time.monotonic() + 15
                self.report("error", "wire-pod exited. Check logs/vector-services.log; retrying in 15 seconds.")
            elif time.monotonic() - self.started > 20 and not self.server_ready:
                self.stop_child()
                self.retry_at = time.monotonic() + 15
                self.report("error", "wire-pod startup timed out. Check logs/vector-services.log.")
            elif self.server_ready and self.plugin_ready:
                config = self.speech_config.resolve()
                voice_ready = bool(config.get("provider") == "openai" and not config.get("base_url") and config.get("api_key"))
                voice_error = self.status().get("voice_error")
                self.report("voice_error" if voice_error else "ready" if voice_ready else "needs_key",
                    voice_error or "Local Vector services running. Say ‘Hey Vector’, then ‘Dimensional …’ in HumanCLI." if voice_ready else
                    "Vector services are running. Configure an OpenAI key in HumanCLI for microphone transcription.",
                    voice_ready=voice_ready)
            return
        if time.monotonic() < self.retry_at:
            return
        try:
            self.validate_bundle()
        except (OSError, ValueError):
            self.report("missing_runtime", "This build is missing a valid local wire-pod runtime. Reinstall the desktop application.")
            self.retry_at = time.monotonic() + 15
            return
        host = host_address(target["ip"])
        env = self.environment(host)
        self.report("checking", "Checking for another wire-pod host on Vector's network", host=host)
        result = subprocess.run([str(self.bundle / "wirepod"), "probe"], env=env, capture_output=True, timeout=5)
        if result.returncode:
            self.report("network_error", "Could not check Vector's local network. Check Wi-Fi and local network permission.")
            self.retry_at = time.monotonic() + 15
            return
        hosts = json.loads(result.stdout).get("hosts", [])
        if hosts:
            self.report("conflict", "Another wire-pod host is advertising escapepod.local. Stop it before using this computer.", peers=sorted(set(hosts)))
            self.retry_at = time.monotonic() + 10
            return
        # Reject existing listeners, never kill or reuse another application's service.
        for address, port in ((host, 8084), ("127.0.0.1", 18084)):
            with socket.socket() as check:
                try:
                    check.bind((address, port))
                except OSError:
                    self.report("conflict", f"Port {port} is already in use. Stop the other wire-pod instance.")
                    self.retry_at = time.monotonic() + 10
                    return
        self.prepare(target)
        # A disconnect may have arrived during the mDNS probe/preparation.
        with self.supervisor.lock:
            if self.supervisor.target != target or self.stop_event.is_set():
                return
            self.report("starting", "Starting local Vector services", host=host, peers=[])
            log_path = self.settings.root / "logs" / "vector-services.log"
            log_path.parent.mkdir(exist_ok=True, mode=0o700)
            if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
                log_path.replace(log_path.with_suffix(".previous.log"))
            self.log = open(log_path, "ab", buffering=0, opener=lambda p, f: os.open(p, f, 0o600))
            self.child = subprocess.Popen([str(self.bundle / "wirepod")], cwd=self.root, env=env,
                                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, start_new_session=True)
            self.started = time.monotonic()
            self.plugin_ready = self.server_ready = False
            threading.Thread(target=self._output, args=(self.child, self.log), daemon=True).start()

    def _output(self, child, log):
        try:
            for line in child.stdout:
                log.write(line)
                if child is self.child:
                    if b"DIMENSIONAL_PLUGIN_READY" in line:
                        self.plugin_ready = True
                    if b"wire-pod started successfully" in line:
                        self.server_ready = True
        except (OSError, ValueError):
            pass
        finally:
            child.stdout.close()

    def stop_child(self):
        child, self.child = self.child, None
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
            if self.log:
                self.log.close()
                self.log = None
        self.plugin_ready = self.server_ready = False
        self.voice_result()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
        else:
            self.stop_child()
