"""Loopback relay lifecycle. Tokens never appear in command lines or logs."""

import json
import secrets
import threading
from pathlib import Path


class ConsoleRelay:
    def __init__(self, settings):
        self.settings = settings
        self.viewer_token = secrets.token_urlsafe(32)
        self.robot_token = secrets.token_urlsafe(32)
        self.process = None
        self.error = None
        self.done = threading.Event()
        self.monitor = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.settings.relay_port}"

    def _new_process(self):
        from dimos.web.relay_bridge.relay_process import RelayProcess

        return RelayProcess(
            port=self.settings.relay_port,
            host="127.0.0.1",
            web_dir=Path(__file__).resolve().parent.parent / "vendor/dimos-web",
            auth_file=self.settings.root / "relay-auth.json",
        )

    def start(self):
        auth_file = self.settings.root / "relay-auth.json"
        auth_file.touch(mode=0o600, exist_ok=True)
        auth_file.chmod(0o600)
        auth_file.write_text(
            json.dumps(
                {
                    "robots": {"go2-space-console": self.robot_token},
                    "viewers": {"local-console": self.viewer_token},
                }
            )
        )
        self.process = self._new_process()
        try:
            self.process.start()
        except Exception as error:
            self.error = str(error)
            self.process.stop()
            raise
        self.monitor = threading.Thread(target=self._watch, daemon=True)
        self.monitor.start()

    def _watch(self):
        while not self.done.wait(2):
            if self.process and not self.process.is_running():
                try:
                    self.process.stop()
                    self.process = self._new_process()
                    self.process.start()
                    self.error = None
                except Exception as error:
                    self.error = str(error)

    def stop(self):
        self.done.set()
        if self.monitor:
            self.monitor.join(timeout=25)
        if self.process:
            self.process.stop()

    def info(self):
        return {"url": self.url, "token": self.viewer_token, "robot": "go2-space-console"}
