from pathlib import Path
import ipaddress
import json
import math
import os
import secrets
import signal
import shutil
import socket
import subprocess
import threading
import tempfile
import time

from dotenv import dotenv_values
import requests

from go2_setup.catalog import Catalog
from go2_setup.control import go2_sensor_recent
from go2_setup.config import Settings
from go2_setup.diagnostics import FailureDiagnostics
from go2_setup.records import inspect_recording
from go2_setup.profiles import profile, require, module_plan
from go2_setup.robots import Robots
from go2_setup.vector.errors import read_startup_error


class Supervisor:
    def __init__(self, settings: Settings, catalog: Catalog):
        self.settings = settings
        self.catalog = catalog
        self.lock = threading.RLock()
        self.connection = "offline"
        self.error = None
        self.ip = ""
        self.target = None
        self.process = None
        self.token = secrets.token_urlsafe(32)
        self.telemetry = {}
        self.mode = "idle"
        self.epoch = 0
        self.session = None
        self.segment = None
        self.done = threading.Event()
        self.started = 0.0
        self.last_ok = 0.0
        self.next_retry = 0.0
        self.stats_cache = None
        self.stats_at = 0.0
        self.diagnostics = FailureDiagnostics(settings.root)
        self.retry_count = 0
        self.last_discovery = 0.0
        self.profile = profile("legacy")
        self.robot_id = None
        # Single connection: modules are added to the running session, never by restarting.
        self.loading_modules = False
        self.hold = False
        self.env = (
            {
                k: v
                for k, v in dotenv_values(settings.env_file).items()
                if v and k in {"ROBOT_IP", "UNITREE_AES_128_KEY"}
            }
            if settings.env_file.exists()
            else {}
        )
        self.ip = self.env.get("ROBOT_IP", "")
        self.connection_file = settings.root / "connection.json"
        try:
            saved = json.loads(self.connection_file.read_text())
            address = ipaddress.ip_address(saved["ip"])
            if (
                saved.get("serial") == settings.serial
                and address.version == 4
                and address.is_private
                and not address.is_loopback
                and not address.is_multicast
            ):
                self.ip = str(address)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.robots = Robots(settings.root, self.ip, settings.serial)
        threading.Thread(target=self._monitor, daemon=True).start()

    @property
    def robot_kind(self):
        return (self.target or {}).get("kind", "go2")

    def remember_ip(self):
        """Remember a successful physical connection without resuming it on startup."""
        if not self.target or self.target.get("replay") or self.robot_kind != "go2":
            return
        fd, name = tempfile.mkstemp(prefix=".connection-", dir=self.settings.root)
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(
                    {"ip": self.ip, "serial": self.target.get("serial", self.settings.serial)}, file
                )
            os.replace(name, self.connection_file)
            if self.robot_id:
                robot = self.robots.get(self.robot_id)
                self.robots.save(robot["name"], self.ip, robot["serial"], ident=self.robot_id)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def call(self, path, body=None, timeout=8):
        response = requests.post(
            f"http://127.0.0.1:{self.settings.runtime_port}{path}",
            json=body or {},
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=timeout,
        )
        if not response.ok:
            raise ValueError(response.json().get("error", "DimOS error"))
        return response.json()

    def connect(self, ip: str | None = None, replay: str | None = None, robot_id=None, config=None):
        if self.settings.replay_only and not replay:
            raise ValueError("Replay-only instance: physical robot connections are disabled")
        with self.lock:
            if self.target or self.process:
                raise ValueError("Disconnect the current session first")
            selected_robot = self.robots.get(robot_id) if robot_id else None
            if selected_robot:
                ip = selected_robot["ip"]
            if not replay:
                address = ipaddress.ip_address(ip or self.ip)
                if (
                    address.version != 4
                    or not address.is_private
                    or address.is_loopback
                    or address.is_multicast
                ):
                    raise ValueError("Enter Go2's private IP address on your Wi-Fi")
                self.ip = str(address)
            kind = selected_robot["kind"] if selected_robot else "go2"
            self.profile = profile(**{**(config or {"preset": "assistant" if kind == "vector" else "legacy"}), "kind": kind})
            self.robot_id = robot_id
            self.loading_modules = False
            self.hold = False
            self.target = {
                "kind": kind,
                "sdk_config": selected_robot.get("sdk_config", "") if selected_robot else "",
                "ip": self.ip,
                "replay": replay,
                "serial": selected_robot["serial"] if selected_robot else self.settings.serial,
            }
            self.connection = "connecting"
            self.error = None
            self.retry_count = 0
            self.next_retry = 0
            self.catalog.event(
                "connection", "Replay requested" if replay else f"{kind} connection requested"
            )

    def _launch(self):
        if self.settings.replay_only and self.target and not self.target.get("replay"):
            raise ValueError("Replay-only instance: physical robot connections are disabled")
        if not self.target:
            return
        if not self.target["replay"] and self.robot_kind == "go2":
            try:
                with socket.create_connection((self.ip, 9991), timeout=1):
                    pass
            except OSError:
                if time.monotonic() - self.last_discovery > 15:
                    self.last_discovery = time.monotonic()
                    try:
                        scan = subprocess.run(
                            [self.settings.python, "-m", "go2_setup.discovery"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                            env={
                                **os.environ,
                                "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                            },
                        )
                        devices = json.loads(scan.stdout.strip().splitlines()[-1])
                        candidate = devices.get(self.target.get("serial", self.settings.serial))
                        if candidate and ipaddress.ip_address(candidate).is_private:
                            self.ip = candidate
                            self.target["ip"] = candidate
                    except (ValueError, IndexError, OSError, subprocess.TimeoutExpired):
                        pass
                self.connection = "reconnecting"
                self.error = f"Go2 is not responding at {self.ip}. Retrying; check whether DHCP changed its IP address."
                self.next_retry = time.monotonic() + 5
                return
        log = (self.settings.root / "runtime.log").open("a")
        args = [
            self.settings.python,
            "-m",
            "go2_setup.vector.runtime" if self.robot_kind == "vector" else "go2_setup.runtime",
            "--port",
            str(self.settings.runtime_port),
            "--navigation-log",
            str(self.settings.root / "runtime.log"),
        ]
        args += ["--replay", self.target["replay"]] if self.target["replay"] else ["--ip", self.ip]
        env = {
            **os.environ,
            **self.env,
            "GO2_RUNTIME_TOKEN": self.token,
            "GO2_SESSION_PROFILE": json.dumps(self.profile),
            "GO2_CONSOLE_URL": f"http://127.0.0.1:{self.settings.port}",
            "GO2_RELAY_URL": self.relay.url,
            "GO2_RELAY_KEY": self.relay.robot_token,
            "GO2_SUPERVISOR_PID": str(os.getpid()),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": "2",
            "NUMBA_CACHE_DIR": str(self.settings.root / "numba-cache"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "lfs.url",
            "GIT_CONFIG_VALUE_0": "https://github.com/dimensionalOS/dimos.git/info/lfs",
        }
        if self.robot_kind == "vector":
            startup_error = self.settings.root / "vector-startup-error.json"
            startup_error.unlink(missing_ok=True)
            env["VECTOR_STARTUP_ERROR_FILE"] = str(startup_error)
            env.pop("UNITREE_AES_128_KEY", None)
            env.pop("ROBOT_IP", None)
            env.update(VECTOR_IP=self.ip, VECTOR_SERIAL=self.target["serial"], VECTOR_SDK_CONFIG=self.target["sdk_config"])
        self.process = subprocess.Popen(
            args,
            cwd=self.settings.runtime,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        log.close()
        self.epoch = 0
        self.mode = "idle"
        self.hold = False
        self.telemetry = {}
        self.connection = "connecting"
        self.started = self.last_ok = time.monotonic()
        self.retry_count += 1

    def _monitor(self):
        while not self.done.wait(0.6):
            try:
                with self.lock:
                    if self.target and not self.process and time.monotonic() >= self.next_retry:
                        self._launch()
                    process = self.process
                if not process:
                    continue
                if process.poll() is not None:
                    error = read_startup_error(self.settings.root / "vector-startup-error.json") if self.robot_kind == "vector" else None
                    self._lost(error or "The DimOS process exited. Check runtime.log.", process)
                    continue
                try:
                    poll_started = time.monotonic()
                    telemetry = self.call("/state", timeout=3)
                except (requests.RequestException, ValueError) as error:
                    self.diagnostics.observe(
                        self.telemetry,
                        elapsed=time.monotonic() - poll_started,
                        segment_id=self.segment["id"] if self.segment else None,
                        error=str(error),
                    )
                    if time.monotonic() - self.last_ok > (
                        180 if self.connection == "connecting" else 12
                    ):
                        self._lost("DimOS did not respond; restarting the connection.", process)
                    continue
                with self.lock:
                    if self.process is not process:
                        continue
                    self.last_ok = time.monotonic()
                    self.accept_telemetry(telemetry)
                    self.diagnostics.observe(
                        self.telemetry,
                        elapsed=time.monotonic() - poll_started,
                        segment_id=self.segment["id"] if self.segment else None,
                    )
                    odom = telemetry.get("sensors", {}).get("odom", {}).get("received", 0)
                    if (
                        go2_sensor_recent(odom, time.time())
                        if self.robot_kind == "go2"
                        else time.time() - odom < 5
                    ):
                        newly_connected = self.connection != "online"
                        self.connection, self.error = "online", None
                        if newly_connected:
                            try:
                                self.remember_ip()
                            except OSError:
                                self.catalog.event("config", "Could not save Go2's IP address")
                            self.catalog.event(
                                "connection",
                                "Replay ready" if self.target["replay"] else ("Vector connected" if self.robot_kind == "vector" else "Go2 connected"),
                            )
                        if self.session and not self.segment:
                            self._begin_segment()
                    elif time.monotonic() - self.started > (
                        90 if self.target["replay"] and self.connection == "connecting" else 40
                    ):
                        self._lost("Robot position updates stopped arriving.", process)
                        continue
                    if self.segment and time.monotonic() - self.stats_at > 5:
                        self.stats_cache = inspect_recording(Path(self.segment["path"]))
                        self.stats_at = time.monotonic()
                    if self.segment and (
                        (telemetry.get("recording") or {}).get("error")
                        or shutil.disk_usage(self.settings.root).free < 2e9
                    ):
                        self.error = "Recording stopped due to an error or low disk space"
                        self.finish_recording()
            except Exception as error:
                self.error = str(error)

    def _end_segment(self, interrupted=False):
        if not self.segment:
            return
        # An interrupted runtime may already be gone. Preserve the last writer
        # counters and error instead of overwriting them with an empty object.
        writer = dict(self.telemetry.get("recording") or {}) if interrupted else {}
        if not interrupted:
            writer = self.call("/record/stop", timeout=40)
        path = Path(self.segment["path"])
        try:
            stats = inspect_recording(path) if path.exists() else None
        except Exception as error:
            stats = None
            writer["error"] = str(error)
            interrupted = True
        self.catalog.update(
            self.segment["id"],
            status="interrupted" if interrupted or writer.get("error") else "closed",
            ended=time.time(),
            stats=stats,
            writer=writer,
        )
        self.segment = None
        self.stats_cache = stats

    def accept_telemetry(self, telemetry):
        """A response requested before a mode switch cannot restore its old authority."""
        if telemetry["control"]["epoch"] >= self.epoch:
            self.mode = telemetry["control"]["mode"]
            self.epoch = telemetry["control"]["epoch"]
        else:
            telemetry = {
                **telemetry,
                "control": {**telemetry["control"], "mode": self.mode, "epoch": self.epoch},
            }
        pose, previous = telemetry.get("pose"), self.telemetry.get("pose")
        if pose and previous and telemetry.get("motion"):
            now = telemetry.get("sensors", {}).get("odom", {}).get("received", 0)
            before = self.telemetry.get("sensors", {}).get("odom", {}).get("received", 0)
            dt = now - before
            if 0.05 < dt < 3:
                delta = pose["yaw"] - previous["yaw"]
                telemetry["motion"]["observed_speed"] = (
                    math.hypot(pose["x"] - previous["x"], pose["y"] - previous["y"]) / dt
                )
                telemetry["motion"]["observed_yaw_rate"] = (
                    abs(math.atan2(math.sin(delta), math.cos(delta))) / dt
                )
        self.telemetry = telemetry

    def _lost(self, error, expected_process=None):
        with self.lock:
            if expected_process is not None and self.process is not expected_process:
                return
            try:
                report = self.diagnostics.save(
                    error, segment_id=self.segment["id"] if self.segment else None
                )
                if self.segment:
                    self.catalog.update(
                        self.segment["id"], interruption_reason=error, diagnostics_path=str(report)
                    )
            except OSError:
                # Diagnostic storage failure must not prevent connection recovery.
                pass
            if self.process and self.process.poll() is None:
                self._terminate()
            self._end_segment(interrupted=True)
            self.process = None
            self.mode = "idle"
            self.epoch += 1
            self.telemetry = {}
            self.error = error
            if self.target and self.target["replay"]:
                self.target = None
                self.connection = "offline"
            else:
                self.connection = "reconnecting" if self.target else "offline"
                self.next_retry = time.monotonic() + min(20, 2 ** min(self.retry_count, 4))
            self.catalog.event("connection", error)

    def _terminate(self):
        process = self.process
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)

    def disconnect(self):
        with self.lock:
            self.target = None
            try:
                if self.connection == "online":
                    self.call("/halt")
                    self._end_segment()
                else:
                    self._end_segment(interrupted=True)
            finally:
                self._terminate()
                self.process = None
                self.connection = "offline"
                self.loading_modules = False
                self.hold = False
                self.mode = "idle"
                self.epoch += 1
                self.telemetry = {}
            if self.session:
                self.catalog.update(self.session["id"], status="closed", ended=time.time())
                self.session = None

    def add_modules(self, preset, modules):
        """Start the session: add the selected modules to the running connection.

        Loading runs in the background so telemetry keeps flowing; the profile is
        recorded first, so a reconnect during loading relaunches with every module.
        """
        config = profile(preset, kind=self.robot_kind, modules=modules)
        with self.lock:
            if not self.target or self.connection != "online":
                raise ValueError("Wait for the robot to connect")
            if self.profile.get("preset") != "base":
                raise ValueError("The blueprint cannot change once the session has started")
            if self.loading_modules:
                raise ValueError("Modules are already loading")
            if self.mode != "idle" or self.session:
                raise ValueError("Pause movement and save the recording first")
            previous, self.profile, self.loading_modules = self.profile, config, True
            robot_id = self.robot_id

        def load():
            try:
                self.call("/modules", {"profile": config}, timeout=180)
                if robot_id:
                    self.robots.remember_profile(robot_id, config)
                self.catalog.event("profile", f"Session started with {len(config['modules'])} modules")
            except Exception as error:
                with self.lock:
                    if self.profile is config:
                        self.profile = previous
                    self.error = f"Could not start the session: {error}"
            finally:
                with self.lock:
                    self.loading_modules = False

        threading.Thread(target=load, daemon=True).start()
        return {"ok": True, "loading": True, "profile": config}

    def set_hold(self, on):
        """Movement toggle: when on, the robot stays in place in every mode."""
        with self.lock:
            if self.connection != "online":
                raise ValueError("Connect the robot first")
            self.call("/hold", {"on": bool(on)}, timeout=10)
            self.hold = bool(on)
            self.catalog.event("control", "Movement off" if self.hold else "Movement on")
            return {"ok": True, "hold": self.hold}

    def require_session(self):
        """Nothing moves before START: the base connection is for choosing modules."""
        if self.profile.get("preset") == "base":
            raise ValueError("Start the session before driving")
        if self.loading_modules:
            raise ValueError("Modules are loading. Wait a moment.")

    def change_mode(self, mode):
        with self.lock:
            if self.connection != "online":
                raise ValueError("Go2 is not connected")
            if mode != "idle":
                self.require_session()
            required = {"teleop": "teleop", "agent": "humancli", "explore": "exploration"}.get(mode)
            if required:
                require(self.profile, required)
            if mode == "explore" and not self.telemetry.get("map"):
                raise ValueError("Wait for the navigation map")
            result = self.call("/mode", {"mode": mode}, timeout=20)
            self.mode, self.epoch = result["mode"], result["epoch"]
            self.catalog.event("mode", f"Control: {mode}")
            return result

    def start_recording(self, space_id):
        with self.lock:
            require(self.profile, "recording")
            if self.session:
                raise ValueError("A recording session is already active")
            if self.connection != "online":
                raise ValueError("Connect Go2 or a replay first")
            if shutil.disk_usage(self.settings.root).free < 3e9:
                raise ValueError("At least 3 GB of free space is required")
            space = self.catalog.get(space_id, "space")
            self.session = self.catalog.folder_item(
                "session",
                space,
                status="recording",
                source="replay" if self.target["replay"] else "robot",
                robot_id=self.robot_id,
                profile=self.profile,
            )
            self._begin_segment()
            return self.session

    def _begin_segment(self):
        segment = self.catalog.folder_item(
            "segment", self.session, status="recording", frame_epoch=secrets.token_hex(8)
        )
        path = str(Path(segment["folder"]) / "raw.db")
        self.segment = self.catalog.update(segment["id"], path=path)
        try:
            self.call("/record/start", {"path": path}, timeout=20)
        except Exception:
            self.catalog.update(segment["id"], status="failed")
            self.segment = None
            raise
        self.stats_cache = None

    def finish_recording(self):
        with self.lock:
            if not self.session:
                raise ValueError("No recording is active")
            self._end_segment(interrupted=self.connection != "online")
            result = self.catalog.update(self.session["id"], status="closed", ended=time.time())
            self.session = None
            return result

    def session_stats(self):
        if not self.session:
            return self.stats_cache
        items = [
            s.get("stats")
            for s in self.catalog.list("segment", self.session["id"])
            if s.get("stats")
        ]
        if self.segment and self.stats_cache:
            items.append(self.stats_cache)
        if not items:
            return None
        result = {"physical_bytes": 0, "duration": 0, "streams": {}}
        for item in items:
            result["physical_bytes"] += item["physical_bytes"]
            result["duration"] += item["duration"]
            for name, values in item["streams"].items():
                dest = result["streams"].setdefault(
                    name, {"bytes": 0, "count": 0, "poses": 0, "gaps_over_1s": 0}
                )
                for field in dest:
                    dest[field] += values.get(field, 0)
        result["gb_per_min"] = (
            result["physical_bytes"] / 1e9 / (result["duration"] / 60) if result["duration"] else 0
        )
        return result

    def snapshot(self):
        telemetry = {k: v for k, v in self.telemetry.items() if k != "camera"}
        return dict(
            robot_id=self.robot_id,
            robot_kind=self.robot_kind,
            profile=self.profile,
            modules=module_plan(self.profile),
            selected_modules=self.profile.get("modules"),
            loading_modules=self.loading_modules,
            hold=self.hold,
            connection=self.connection,
            error=self.error,
            ip=self.ip,
            replay=bool(self.target and self.target["replay"]),
            mode=self.mode,
            epoch=self.epoch,
            telemetry=telemetry,
            session=self.session,
            segment=self.segment,
            stats=self.session_stats(),
            disk_free=shutil.disk_usage(self.settings.root).free,
            storage_root=str(self.settings.root),
            runtime_log=str(self.settings.root / "runtime.log"),
            agent_available=True,
        )

    def close(self):
        self.done.set()
        self.disconnect()
