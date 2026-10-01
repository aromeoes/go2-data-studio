"""Restricted local wire-pod bridge, separate from robot and desktop credentials."""

import math
import os
import secrets
import threading
import time

from pydantic import BaseModel, ConfigDict, Field


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    serial: str = Field(min_length=1, max_length=100)
    robot_id: str
    conversation_id: str
    epoch: int
    issued: float = Field(allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=2000)


class WirePodVoice:
    def __init__(self, root, supervisor, agent):
        self.path = root / "vector-wirepod-token"
        self.supervisor, self.agent = supervisor, agent
        self.lock = threading.RLock()
        self.seen = {}
        # Opt-in: no token is created until local setup explicitly enables this route.
        self.token = self.path.read_text().strip() if self.path.is_file() else None

    def enable(self):
        with self.lock:
            if self.token is None:
                token = secrets.token_urlsafe(32)
                with open(self.path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
                    f.write(token)
                self.token = token
            return {
                "enabled": True,
                "token_path": str(self.path),
                "transport": "Local loopback",
                "services": self.services.status() if hasattr(self, "services") else {"state": "stopped"},
            }

    def authorized(self, authorization):
        return bool(self.token and secrets.compare_digest(authorization, "Bearer " + self.token))

    def session(self):
        s = self.supervisor
        with s.lock:
            if (
                s.robot_kind != "vector"
                or s.connection != "online"
                or s.mode != "agent"
                or "voice" not in s.profile["enabled"]
            ):
                raise ValueError("Enable Vector HumanCLI and voice input in the application first")
            if self.agent.busy:
                raise ValueError("HumanCLI is busy")
            return dict(
                robot_id=s.robot_id,
                serial=s.target["serial"],
                epoch=s.epoch,
                conversation_id=self.agent.snapshot()["conversation_id"],
                issued=time.time(),
            )

    def submit(self, data):
        with self.lock, self.supervisor.lock:
            session = self.session()
            if not math.isfinite(data.issued) or not 0 <= time.time() - data.issued <= 8:
                raise ValueError("Voice request expired")
            if any(
                getattr(data, key) != session[key]
                for key in ("robot_id", "serial", "epoch", "conversation_id")
            ):
                raise ValueError("The Vector voice session changed")
            self.seen = {k: v for k, v in self.seen.items() if time.time() - v < 60}
            if data.id in self.seen:
                raise ValueError("Voice request was already received; it will not be replayed")
            if len(self.seen) >= 100:
                raise ValueError("Too many voice requests")
            self.seen[data.id] = time.time()
            return self.agent.submit(data.text, data.epoch, None)
