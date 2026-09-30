import json
import time
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from go2_setup.localization import MatchAcceptance, selected_map, transform_pose
from go2_setup.catalog import Catalog
from go2_setup.config import Settings
from go2_setup.api import create_app


def make_map(catalog):
    (catalog.root / "spaces").mkdir(exist_ok=True)
    space = catalog.space("Apartment")
    session = catalog.folder_item("session", space, status="closed")
    segment = catalog.folder_item("segment", session, status="closed")
    item = catalog.folder_item("map", segment, status="ready")
    path = catalog.root / "saved.pc2.lcm"
    path.write_bytes(b"test map")
    return catalog.update(item["id"], map_path=str(path)), space


def test_map_identity_checks_file_status_and_space(tmp_path):
    catalog = Catalog(tmp_path)
    item, space = make_map(catalog)
    selection = selected_map(catalog, item["id"])
    assert selection["space_id"] == space["id"]
    assert len(selection["fingerprint"]) == 64
    catalog.update(item["id"], status="failed")
    with pytest.raises(ValueError, match="completed"):
        selected_map(catalog, item["id"])
    catalog.update(item["id"], status="ready", map_path="/etc/hosts")
    with pytest.raises(ValueError, match="outside"):
        selected_map(catalog, item["id"])


def test_matching_requires_consistency_and_rejects_weak_tilted_and_invalid_fixes():
    gate = MatchAcceptance()
    identity = np.eye(4)
    assert not gate.evaluate(identity, 0.9, 0.04)[0]
    assert not gate.evaluate(identity, 0.9, 0.04)[0]
    assert gate.evaluate(identity, 0.9, 0.04)[0]
    assert not gate.evaluate(identity, 0.4, 0.04)[0]
    assert gate.count == 0
    assert not gate.evaluate(identity, 0.95, 0.2)[0]
    tilted = np.diag([1.0, -1.0, -1.0, 1.0])
    assert not gate.evaluate(tilted, 1, 0.01)[0]
    assert not gate.evaluate(np.full((4, 4), float("nan")), 1, 0.01)[0]
    gate.evaluate(identity, 0.95, 0.03)
    distant = identity.copy()
    distant[0, 3] = 3
    assert not gate.evaluate(distant, 0.95, 0.03)[0] and gate.count == 1


def test_map_selection_requires_idle_and_saved_recording_and_persists(tmp_path, monkeypatch):
    app = create_app(Settings(root=tmp_path, env_file=tmp_path / "absent"))
    supervisor = app.state.supervisor
    monkeypatch.setattr(supervisor, "_launch", lambda: None)
    item, _ = make_map(supervisor.catalog)
    headers = {"X-Go2-Request": "1"}
    with TestClient(app) as client:
        supervisor.mode = "teleop"
        assert (
            client.post(
                "/api/localization", headers=headers, json={"map_id": item["id"]}
            ).status_code
            == 409
        )
        supervisor.mode = "idle"
        supervisor.session = {"id": "active"}
        assert (
            client.post(
                "/api/localization", headers=headers, json={"map_id": item["id"]}
            ).status_code
            == 409
        )
        supervisor.session = None
        assert (
            client.post(
                "/api/localization", headers=headers, json={"map_id": item["id"]}
            ).status_code
            == 200
        )
        assert json.loads((tmp_path / "localization.json").read_text())["map_id"] == item["id"]
        assert client.get("/api/state").json()["localization_map_id"] == item["id"]
        assert (
            client.post("/api/localization", headers=headers, json={"map_id": None}).status_code
            == 200
        )


def test_blueprint_uses_official_go2_relocalization_and_merged_costmap():
    from go2_setup.runtime import build_blueprint
    from go2_setup.profiles import profile
    from dimos.mapping.relocalization.go2.module import Go2Relocalization

    graph = build_blueprint(
        profile("assistant"), replay="fixture.db", localization={"path": "saved.pc2.lcm"}
    )
    modules = {b.module.__name__: b for b in graph.blueprints}
    assert issubclass(modules["ConsoleRelocalization"].module, Go2Relocalization)
    assert "CostMapper" in modules
    preview = build_blueprint(profile("preview"), localization={"path": "saved.pc2.lcm"})
    assert not any(b.module.__name__ == "ConsoleRelocalization" for b in preview.blueprints)


def test_selected_map_blocks_all_autonomous_velocities_but_keeps_teleop(monkeypatch):
    from go2_setup.modules import ControlGate
    from dimos.msgs.geometry_msgs.Twist import Twist

    monkeypatch.setattr("go2_setup.modules.Module.__init__", lambda self, **kwargs: None)
    monkeypatch.setenv("GO2_LOCALIZATION", '{"id":"map"}')
    gate = ControlGate()
    gate.cmd_vel = Mock()
    gate.teleop_requested = Mock()
    gate.last_odom = gate.last_lidar = gate.last_map = time.monotonic()
    with pytest.raises(ValueError, match="relocalization"):
        gate.switch("explore")
    epoch = gate.switch("agent")
    with pytest.raises(ValueError, match="relocalization"):
        gate.navigation(epoch, True)
    token = gate.switch("teleop")
    assert gate.teleop(token, 0.1, 0, 0)
    gate.halt()
    gate.localization_state(True)
    assert gate.authority.mode == "idle"  # a fix never starts motion
    gate.switch("explore")
    gate._nav(Twist((0.1, 0, 0)))
    assert gate.nav_forwarded == 1
    gate.localization_ok_at -= 4
    gate._nav(Twist((0.1, 0, 0)))
    assert gate.nav_forwarded == 1
    gate.done = Mock()
    gate.done.wait.side_effect = [False, True]
    gate._watchdog()
    assert gate.authority.mode == "idle"
    assert not gate.cmd_vel.publish.call_args.args[0]


def test_named_places_survive_reconnect_only_with_the_exact_localized_map(tmp_path):
    from go2_setup.robot_skills import Places
    from dimos.types.robot_location import RobotLocation

    first = np.eye(4)
    first[:2, 3] = [3, -2]
    state = {
        "id": "map1",
        "fingerprint": "abc",
        "space_id": "home",
        "status": "localized",
        "world_from_map": first.tolist(),
    }
    places = Places(tmp_path, "runtime1", lambda: state)
    places.space = "home"
    places.yaw = 0.3
    places.tag_location(RobotLocation(name="Desk", position=[4, 0, 0], rotation=[0, 0, 0.3]))
    second = np.eye(4)
    second[:2, 3] = [-2, 4]
    state["world_from_map"] = second.tolist()
    reloaded = Places(tmp_path, "runtime2", lambda: state)
    reloaded.space = "home"
    value = reloaded.query_tagged_location("desk")
    assert value.position == pytest.approx([-1, 6, 0])
    assert reloaded.list()[0]["usable"]
    state["status"] = "localizing"
    assert not reloaded.list()[0]["usable"]
    with pytest.raises(ValueError, match="relocalization"):
        reloaded.query_tagged_location("desk")
    state["status"] = "localized"
    state["fingerprint"] = "changed"
    assert not reloaded.list()[0]["usable"]
    with pytest.raises(ValueError, match="earlier connection"):
        reloaded.query_tagged_location("desk")


def test_coordinate_roundtrip_preserves_heading_and_position():
    matrix = np.array([[0.0, -1.0, 0, 4], [1.0, 0, 0, 2], [0, 0, 1, 0], [0, 0, 0, 1]])
    pose = dict(x=2, y=-3, z=0.4, yaw=0.5)
    mapped = transform_pose(matrix, pose)
    assert mapped["x"] == 7 and mapped["y"] == 4
    assert transform_pose(np.linalg.inv(matrix), mapped) == pytest.approx(pose)


def test_candidate_needs_operator_confirmation_and_a_fresh_merged_map():
    import threading
    from go2_setup.relocalization_module import ConsoleRelocalization

    module = object.__new__(ConsoleRelocalization)
    module._status_lock = threading.RLock()
    module._status = dict(status="verifying", merged_at=time.time())
    module._confirmed = False
    with pytest.raises(ValueError, match="candidate"):
        module.confirm()
    module._status.update(status="candidate", merged_at=time.time() - 11)
    with pytest.raises(ValueError, match="fresh"):
        module.confirm()
    module._status["merged_at"] = time.time()
    assert module.confirm() == {"ok": True}
    assert module.state()["status"] == "localized" and module._confirmed


def test_flat_floor_geometry_is_rejected_before_matching():
    import open3d as o3d
    from go2_setup.relocalization_module import registration_cloud

    floor = o3d.geometry.PointCloud()
    x, y = np.meshgrid(np.linspace(-3, 3, 100), np.linspace(-3, 3, 100))
    floor.points = o3d.utility.Vector3dVector(
        np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])
    )
    with pytest.raises(ValueError, match="structural points"):
        registration_cloud(floor)


def test_local_map_loader_does_not_invoke_git_or_dataset_discovery(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from reactivex import Subject
    from go2_setup.relocalization_module import ConsoleRelocalization
    import dimos.utils.data

    monkeypatch.setattr(
        dimos.utils.data,
        "get_data",
        Mock(side_effect=AssertionError("must not discover a repository")),
    )
    cloud = SimpleNamespace(frame_id="world")
    decoder = Mock(return_value=cloud)
    monkeypatch.setattr("go2_setup.relocalization_module.PointCloud2.lcm_decode", decoder)
    module = object.__new__(ConsoleRelocalization)
    module.config = SimpleNamespace(map_frame="map", republish_loaded_map=0)
    module.fixes = Subject()
    module.loaded_map = Mock()
    disposables = []
    module.register_disposable = disposables.append
    path = tmp_path / "saved.pc2.lcm"
    path.write_bytes(b"fixture")
    module._load_premap(str(path))
    assert module.premap is cloud and cloud.frame_id == "map"
    decoder.assert_called_once_with(b"fixture")
    module.fixes.on_next(object())
    module.loaded_map.publish.assert_called_once_with(cloud)
    for disposable in disposables:
        disposable.dispose()


def test_bad_reference_map_does_not_abort_the_robot_blueprint(monkeypatch):
    import threading
    from go2_setup.relocalization_module import ConsoleRelocalization

    module = object.__new__(ConsoleRelocalization)
    module._status_lock = threading.RLock()
    module._status = {"status": "loading"}
    module._initialize = Mock(side_effect=ValueError("map is corrupt"))
    module.start()
    assert module.state()["status"] == "error"
    assert "map is corrupt" in module.state()["message"]


@pytest.mark.parametrize("fitness,rmse,code,text", [
    (0.79, 0.07, "low_overlap", "79.0%"),
    (0.95, 0.09, "high_error", "9.0 cm"),
    (float("nan"), 0.01, "invalid_result", "invalid"),
])
def test_rejection_explains_the_failed_measurement(fitness, rmse, code, text):
    gate = MatchAcceptance()
    gate.evaluate(np.eye(4), 0.98, 0.02)
    accepted, message = gate.evaluate(np.eye(4), fitness, rmse)
    assert not accepted and gate.count == 0 and gate.previous is None
    assert gate.reason == code and text in message


def test_high_overlap_cannot_hide_a_tilted_or_inconsistent_alignment():
    gate = MatchAcceptance()
    accepted, message = gate.evaluate(np.diag([1., -1., -1., 1.]), 0.99, 0.01)
    assert not accepted and gate.reason == "tilted_alignment" and "180.0°" in message
    gate.evaluate(np.eye(4), 0.99, 0.01)
    moved = np.eye(4)
    moved[0, 3] = 1
    accepted, message = gate.evaluate(moved, 0.99, 0.01)
    assert not accepted and gate.reason == "inconsistent_alignment"
    assert gate.count == 1 and "Restarting verification" in message


def test_matching_consumes_mapper_history_not_recent_lidar_or_merged_output():
    from types import SimpleNamespace
    from reactivex import Subject
    from go2_setup.relocalization_module import ConsoleRelocalization

    module = object.__new__(ConsoleRelocalization)
    module.config = SimpleNamespace(reloc_interval=0.01)
    mapped, lidar, merged = Subject(), Subject(), Subject()
    module.global_map = SimpleNamespace(observable=lambda: mapped)
    module.lidar = SimpleNamespace(observable=lambda: lidar)
    module.merged_map = SimpleNamespace(observable=lambda: merged)
    seen = []
    subscription = module.clouds().subscribe(seen.append)
    try:
        lidar.on_next("latest scan")
        merged.on_next("saved plus live map")
        assert seen == []
        mapped.on_next("all mapped views")
        assert seen == ["all mapped views"]
    finally:
        subscription.dispose()


def test_rejected_candidate_is_logged_but_never_published(monkeypatch):
    import threading
    from types import SimpleNamespace
    from go2_setup.relocalization_module import ConsoleRelocalization

    module = object.__new__(ConsoleRelocalization)
    module._status_lock = threading.RLock()
    module._status = dict(attempts=0, world_from_map=None)
    module._acceptance = MatchAcceptance()
    module.keep_relocalizing = lambda: True
    module.submit = Mock()
    query = SimpleNamespace(points=np.array([[0, 0, 0], [1, 2, 3]]))
    monkeypatch.setattr("go2_setup.relocalization_module.registration_cloud", lambda _: query)
    module._relocalizer = SimpleNamespace(align=lambda _: SimpleNamespace(
        transformation=np.eye(4), fitness=0.79, inlier_rmse=0.07))
    class Message:
        pointcloud = object()
        def __len__(self):
            return 1234
    logger = Mock()
    monkeypatch.setattr("go2_setup.relocalization_module.logger", logger)
    module._relocalize(Message())
    state = module.state()
    assert state["world_from_map"] is None
    assert state["rejection_reason"] == "low_overlap"
    assert state["structural_points"] == 2 and state["points"] == 1234
    module.submit.assert_not_called()
    diagnostic = logger.info.call_args.kwargs
    assert "candidate_map_from_world" in diagnostic
    assert diagnostic["rejection_reason"] == "low_overlap"
