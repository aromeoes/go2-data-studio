"""Application channels on the official DimOS relay bridge.

SDK transport acknowledgements are distinct from command completion. Results are
correlated by id, never retried, and retained briefly for a late subscription.
"""

import json
import os
import queue
import threading
import time
import urllib.request
import urllib.error

from reactivex.disposable import Disposable
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.stream import In, Out
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.sensor_msgs.Image import Image
from dimos.web.cockpit import Channel, Teleop, cockpit
from dimos.web.codecs import EncodedPayload, web_encoder


@web_encoder("console.text.json.v1")
def encode_console_text(msg: str) -> EncodedPayload:
    return EncodedPayload(json.dumps(msg).encode())


class ConsoleSDK(Module):
    console_command: In[str]
    console_heartbeat: In[str]
    console_state: Out[str]
    console_results: Out[str]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.done = threading.Event()
        self.commands = queue.Queue(maxsize=16)
        self.beats = queue.Queue(maxsize=1)
        self.urgent = queue.Queue(maxsize=4)
        self.results = {}
        self.seen = set()
        self.lock = threading.Lock()

    @rpc
    def start(self):
        super().start()
        self.register_disposable(Disposable(self.console_command.subscribe(self._command)))
        self.register_disposable(Disposable(self.console_heartbeat.subscribe(self._heartbeat)))
        for target in (
            self._state_loop,
            self._command_loop,
            self._heartbeat_loop,
            self._urgent_loop,
        ):
            threading.Thread(target=target, daemon=True).start()

    def _request(self, path, data=None):
        req = urllib.request.Request(
            os.environ["GO2_CONSOLE_URL"] + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Go2-Request": "1",
                "Authorization": "Bearer " + os.environ["GO2_RUNTIME_TOKEN"],
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = json.load(error).get("detail", "Command rejected")
            raise ValueError(str(detail)) from None

    def _command(self, raw):
        try:
            item = json.loads(raw)
            ident = item["id"]
            if not isinstance(ident, str) or len(ident) > 80:
                return
            with self.lock:
                if ident in self.seen:
                    return
                # Bounded history; commands also expire at the application boundary.
                if len(self.seen) > 4096:
                    self.seen = set(self.results)
                self.seen.add(ident)
            (self.urgent if item.get("path") == "/stop" else self.commands).put_nowait(item)
        except queue.Full:
            self._result(ident, error="Command queue is busy; try again")
        except (KeyError, TypeError, ValueError):
            return

    def _heartbeat(self, raw):
        try:
            item = json.loads(raw)
            if item.get("path") != "/heartbeat":
                return
            try:
                self.beats.get_nowait()
            except queue.Empty:
                pass
            self.beats.put_nowait(item)
        except (TypeError, ValueError, queue.Full):
            pass

    def _result(self, ident, value=None, error=None):
        with self.lock:
            self.results[ident] = {"id": ident, "value": value, "error": error, "at": time.time()}
            self.results = {k: v for k, v in self.results.items() if time.time() - v["at"] < 60}

    def _command_loop(self):
        self._consume(self.commands)

    def _urgent_loop(self):
        self._consume(self.urgent)

    def _consume(self, commands):
        while not self.done.is_set():
            try:
                item = commands.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._result(item["id"], value=self._request("/api/sdk/command", item))
            except Exception as error:
                self._result(item["id"], error=str(error))

    def _heartbeat_loop(self):
        while not self.done.is_set():
            try:
                item = self.beats.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._request("/api/sdk/command", item)
            except Exception:
                # The product lease expires if renewals fail.
                pass

    def _state_loop(self):
        while not self.done.wait(0.25):
            try:
                state = self._request("/api/sdk/state")
                self.console_state.publish(json.dumps(state))
                with self.lock:
                    results = list(self.results.values())
                self.console_results.publish(json.dumps(results))
            except Exception:
                # A stopped supervisor is handled by the process parent guard.
                pass

    @rpc
    def stop(self):
        self.done.set()
        super().stop()


def sdk_blueprint(*, max_linear=1.0, max_angular=0.5):
    # Channel-only manifest: no Cockpit panels, layout or UI dependency.
    blueprint = cockpit(
        Teleop(max_linear=max_linear, max_angular=max_angular, boost=1.0),
        channels=[
            Channel("color_image", Image, encoding="jpeg.v1", delivery="latest", max_hz=10),
            Channel("odom", PoseStamped, encoding="pose.json.v1", max_hz=15),
            Channel(
                "global_costmap",
                OccupancyGrid,
                encoding="costmap.zlib.v1",
                delivery="latest",
                max_hz=3,
            ),
            Channel(
                "console_command",
                str,
                dir="tx",
                encoding="text.json.v1",
                publish="shared",
                max_hz=10,
            ),
            Channel(
                "console_heartbeat",
                str,
                dir="tx",
                encoding="text.json.v1",
                publish="shared",
                max_hz=8,
            ),
            Channel("console_state", str, encoding="console.text.json.v1", max_hz=4),
            Channel("console_results", str, encoding="console.text.json.v1", max_hz=4),
        ],
    )
    # Teleop authors the specialized protocol channel. Discard its optional
    # presentation metadata: the application renders its own controls.
    manifest = blueprint.blueprints[0].kwargs["manifest"]
    manifest.update(panels=[], layout=None, pages=[])
    return blueprint
