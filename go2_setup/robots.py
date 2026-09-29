"""Saved robot instances. Connection settings contain references to credentials, never tokens."""

import copy
import ipaddress
import json
from pathlib import Path
import socket
import threading
import uuid

from go2_setup.catalog import atomic_json
from go2_setup.profiles import profile


def private_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("Enter the robot's private IPv4 address") from None
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_multicast
        or str(address) in {"0.0.0.0", "255.255.255.255"}
    ):
        raise ValueError("Enter the robot's private IPv4 address")
    return str(address)


class Robots:
    def __init__(self, root: Path, legacy_ip="", serial=""):
        self.path = root / "robots.json"
        self.lock = threading.RLock()
        self.items = []
        if self.path.exists():
            data = json.loads(self.path.read_text())
            for item in data:
                if item["kind"] not in {"go2", "vector"}:
                    raise ValueError("Unsupported saved robot type")
                item["ip"] = private_ip(item["ip"])
                item["profile"] = profile(**{**item["profile"], "kind": item["kind"]})
            self.items = data
        elif legacy_ip:
            try:
                self.save("My Go2", legacy_ip, serial)
            except ValueError:
                pass

    def list(self):
        with self.lock:
            return copy.deepcopy(self.items)

    def get(self, ident):
        with self.lock:
            item = next((x for x in self.items if x["id"] == ident), None)
            if item is None:
                raise ValueError("Saved robot not found")
            return copy.deepcopy(item)

    def save(self, name, ip, serial="", kind="go2", ident=None, sdk_config=""):
        if kind == "vector":
            from go2_setup.vector.credentials import validate_reference
            sdk_config = validate_reference(sdk_config, serial)
        if kind not in {"go2", "vector"}:
            raise ValueError("Unsupported robot type")
        name, serial = name.strip(), serial.strip()
        if not name or len(name) > 80 or len(serial) > 100:
            raise ValueError("Enter a robot name (up to 80 characters)")
        ip = private_ip(ip)
        with self.lock:
            if any(
                x["id"] != ident and (x["ip"] == ip or (serial and x["serial"] == serial))
                for x in self.items
            ):
                raise ValueError("This robot is already saved")
            item = self.get(ident) if ident else dict(id=uuid.uuid4().hex, profile=profile("assistant" if kind == "vector" else "map-record", kind=kind))
            if ident and item["kind"] != kind:
                raise ValueError("A saved robot cannot change embodiment")
            item.update(name=name, ip=ip, serial=serial, kind=kind)
            if kind == "vector":
                item["sdk_config"] = sdk_config
            self.items = [x for x in self.items if x["id"] != item["id"]] + [item]
            atomic_json(self.path, self.items)
            return copy.deepcopy(item)

    def remember_profile(self, ident, config):
        with self.lock:
            robot = self.get(ident)
            config = profile(**{**config, "kind": robot["kind"]})
            for item in self.items:
                if item["id"] == ident:
                    item["profile"] = config
            atomic_json(self.path, self.items)

    def availability(self):
        # A reachable service is not an authenticated robot identity.
        from concurrent.futures import ThreadPoolExecutor

        def check(item):
            try:
                with socket.create_connection((item["ip"], 443 if item["kind"] == "vector" else 9991), timeout=0.8):
                    return item["id"], "reachable"
            except OSError:
                return item["id"], "unreachable"

        with ThreadPoolExecutor(max_workers=4) as workers:
            return dict(workers.map(check, self.list()))
