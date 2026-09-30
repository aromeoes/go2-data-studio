"""Local library mutations. Never send commands to the robot or delete cloud data."""

from pathlib import Path
import shutil

from go2_setup.catalog import identifier


def remove_segment(ident, catalog, supervisor, jobs, cloud):
    # Serialize with recording/replay, map-job creation and upload startup. Only
    # metadata changes and atomic renames happen under the control locks.
    moved = []
    with supervisor.lock, jobs.lock, cloud.lock:
        segment = catalog.get(ident, "segment")
        if segment.get("backup", {}).get("status") == "complete":
            raise ValueError("Backed-up segments cannot be removed with this action")
        if segment["status"] in {"recording", "importing"} or (
            supervisor.session and supervisor.session["id"] == segment["parent"]
        ):
            raise ValueError("Save the recording or finish the import before deleting this segment")
        if cloud.active == ident or segment.get("backup", {}).get("status") in {
            "preparing",
            "uploading",
            "verifying",
        }:
            raise ValueError(
                "Pause the upload and wait for it to stop before deleting this segment"
            )
        replay = (supervisor.target or {}).get("replay")
        if replay and Path(replay).resolve() == Path(segment["path"]).resolve():
            raise ValueError("Disconnect the replay before deleting this segment")
        maps = catalog.list("map", ident)
        if any(m["id"] == getattr(supervisor, "localization_map_id", None) for m in maps):
            raise ValueError("Switch to the live map before deleting the selected localization map")
        if any(m["status"] in {"queued", "running"} or m["id"] in jobs.processes for m in maps):
            raise ValueError("Wait for map generation to finish before deleting this segment")
        session = catalog.get(segment["parent"], "session")
        space = catalog.get(session["parent"], "space")
        base = catalog.root.resolve()
        expected = base / "spaces" / space["id"] / "sessions" / session["id"] / "segments" / ident
        folder = Path(segment["folder"])
        # Do not follow substituted parent directories or catalog paths outside
        # this exact segment. Imported originals are deliberately never removed.
        if folder != expected or folder.resolve() != expected or not folder.is_dir():
            raise ValueError("Segment folder is missing or outside its expected storage location")
        staging = base / "cloud-staging"
        if staging.resolve() != staging:
            raise ValueError("Cloud staging folder is outside its expected storage location")
        trash = base / ".deleting"
        if trash.resolve() != trash:
            raise ValueError("Deletion folder is outside its expected storage location")
        trash.mkdir(exist_ok=True, mode=0o700)
        tombstone = trash / identifier()
        tombstone.mkdir(mode=0o700)
        try:
            with catalog.db() as db:
                db.execute("BEGIN IMMEDIATE")
                for source in [folder, staging / f"{ident}.db", staging / f"{ident}.partial"]:
                    if source.exists() or source.is_symlink():
                        target = tombstone / source.name
                        source.rename(target)
                        moved.append((source, target))
                db.executemany(
                    "DELETE FROM objects WHERE id=?", [(ident,)] + [(m["id"],) for m in maps]
                )
        except Exception:
            for source, target in reversed(moved):
                target.rename(source)
            tombstone.rmdir()
            raise
    # Large recordings can take time to unlink. Keep robot heartbeat locks free.
    warning = None
    try:
        shutil.rmtree(tombstone)
    except OSError:
        warning = f"Segment removed from library, but some files remain in {tombstone}. Remove that folder to reclaim the remaining space."
    catalog.event("library", f"Deleted local segment {ident[:6]} and {len(maps)} generated maps")
    return {"ok": True, "removed_maps": len(maps), "warning": warning}
