import json
from types import SimpleNamespace
from unittest.mock import Mock

from reactivex.subject import Subject

from go2_setup.catalog import Catalog
from go2_setup.config import Settings
from go2_setup.diagnostics import FailureDiagnostics
from go2_setup.modules import PassiveGo2Connection
from go2_setup.supervisor import Supervisor


def test_failure_report_bounds_history_and_excludes_payloads(tmp_path):
    recorder = FailureDiagnostics(tmp_path)
    telemetry = {
        "camera": "private image bytes",
        "map": {"cells": [1, 2, 3]},
        "sensors": {"odom": {"received": 1, "count": 4}},
        "recording": {"queued": 5, "dropped": 2},
        "control": {"mode": "teleop"},
    }
    for _ in range(100):
        recorder.observe(telemetry, elapsed=0.012, segment_id="segment")
    telemetry["recording"]["queued"] = 999
    report = json.loads(recorder.save("Odom stopped", segment_id="segment").read_text())
    assert len(report["samples"]) == 90
    assert report["samples"][-1]["recording"]["queued"] == 5
    assert report["samples"][-1]["rpc_ms"] == 12
    assert "private image bytes" not in json.dumps(report)
    assert "cells" not in json.dumps(report)


def test_interruption_keeps_writer_state_and_reason(tmp_path):
    settings = Settings(root=tmp_path, env_file=tmp_path / "absent")
    settings.initialize()
    catalog = Catalog(tmp_path)
    supervisor = Supervisor(settings, catalog)
    supervisor.done.set()
    supervisor.target = {"ip": "192.168.1.20", "replay": None}
    supervisor.connection = "online"
    supervisor.call = Mock(return_value={})
    supervisor.start_recording(catalog.space("test")["id"])
    segment = supervisor.segment
    supervisor.telemetry = {"recording": {"dropped": 7, "queued": 3, "error": "disk error"}}
    supervisor.diagnostics.observe(supervisor.telemetry, elapsed=0.02, segment_id=segment["id"])
    supervisor._lost("Position updates stopped")
    saved = catalog.get(segment["id"])
    assert saved["writer"] == {"dropped": 7, "queued": 3, "error": "disk error"}
    assert saved["interruption_reason"] == "Position updates stopped"
    assert json.loads(open(saved["diagnostics_path"]).read())["segment_id"] == segment["id"]
    assert supervisor.connection == "reconnecting"


def test_source_health_distinguishes_stream_error_from_bridge_silence():
    connection = object.__new__(PassiveGo2Connection)
    connection._sensor_health = {}
    connection._lidar_enable = {"requested": None, "error": None}
    connection._lidar_status = {"received": None, "data": None}
    connection.register_disposable = Mock()
    channel = SimpleNamespace(readyState="open", bufferedAmount=100)
    peer = SimpleNamespace(connectionState="connected", iceConnectionState="completed")
    connection.connection = SimpleNamespace(
        conn=SimpleNamespace(
            pc=peer, datachannel=SimpleNamespace(pub_sub=SimpleNamespace(channel=channel))
        )
    )
    source = Subject()
    publish = Mock()
    connection._subscribe_sensor("lidar", source, publish)
    source.on_next("frame")
    source.on_error(ValueError("decode failed"))
    state = connection.transport_state()
    assert state["sensors"]["lidar"]["count"] == 1
    assert state["sensors"]["lidar"]["published"] is not None
    assert state["sensors"]["lidar"]["error"] == "decode failed"
    assert state["channel"] == "open"
    assert state["buffered_bytes"] == 100
    publish.assert_called_once_with("frame")


def test_diagnostic_write_failure_does_not_prevent_reconnection(tmp_path):
    settings = Settings(root=tmp_path, env_file=tmp_path / "absent")
    settings.initialize()
    supervisor = Supervisor(settings, Catalog(tmp_path))
    supervisor.done.set()
    supervisor.target = {"ip": "192.168.1.20", "replay": None}
    supervisor.diagnostics.save = Mock(side_effect=OSError("disk full"))
    supervisor._lost("Position updates stopped")
    assert supervisor.connection == "reconnecting"
