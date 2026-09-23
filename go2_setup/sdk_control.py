"""Application ownership above the SDK's exclusive Teleop lease."""

import threading
import time


class CommandOwner:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.client = None
        self.deadline = 0.0
        self.stopped_at = 0.0

    def authorize(self, item):
        path, client = item.get("path"), item.get("client")
        if not isinstance(client, str) or not 1 <= len(client) <= 80:
            raise ValueError("Missing console identity")
        with self.lock:
            if path == "/stop":
                self.stopped_at = max(self.stopped_at, item["sent"])
                self.client = None
                self.deadline = 0.0
                return
            if item["sent"] <= self.stopped_at:
                raise ValueError("Command cancelled by Stop")
            held = self.client is not None and self.clock() < self.deadline
            if held and client != self.client:
                raise ValueError("Another console has control. Release its controls first.")
            if path == "/heartbeat":
                if not held or client != self.client:
                    raise ValueError("Console control expired; enable it again")
                self.deadline = self.clock() + 2
            elif path == "/mode":
                self.client = client
                self.deadline = self.clock() + 2
            elif path == "/release":
                if client != self.client:
                    raise ValueError("This console does not hold control")
                self.client = None
                self.deadline = 0.0
