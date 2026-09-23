from pathlib import Path
import sqlite3
import re
import math


def inspect_recording(path: Path) -> dict:
    """Inspect recorded payloads without loading/decoding sensor data or modifying the DB."""
    if not path.is_file():
        raise ValueError("Recording does not exist")
    streams = {}
    first, last = math.inf, -math.inf
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        names = [r[0] for r in db.execute("SELECT name FROM _streams")]
        for name in names:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            columns = {r[1] for r in db.execute(f'PRAGMA table_info("{name}")')}
            count, low, high = db.execute(
                f'SELECT count(*),min(ts),max(ts) FROM "{name}"'
            ).fetchone()
            blob_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name=?", (name + "_blob",)
            ).fetchone()
            size = (
                db.execute(f'SELECT coalesce(sum(length(data)),0) FROM "{name}_blob"').fetchone()[0]
                if blob_exists
                else 0
            )
            poses = (
                db.execute(f'SELECT count(*) FROM "{name}" WHERE pose_x IS NOT NULL').fetchone()[0]
                if "pose_x" in columns
                else 0
            )
            gaps = db.execute(
                f'SELECT count(*),coalesce(max(gap),0) FROM (SELECT ts-lag(ts) OVER(ORDER BY ts) AS gap FROM "{name}") WHERE gap>1'
            ).fetchone()
            duration = (high - low) if count else 0
            streams[name] = dict(
                count=count,
                bytes=size,
                duration=duration,
                poses=poses,
                gaps_over_1s=gaps[0],
                max_gap_s=gaps[1],
                hz=count / duration if duration else None,
            )
            if count:
                first, last = min(first, low), max(last, high)
    duration = max(0, last - first) if first != math.inf else 0
    physical = sum(
        p.stat().st_size
        for p in [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]
        if p.exists()
    )
    return dict(
        streams=streams,
        duration=duration,
        first=first if first != math.inf else None,
        last=last if last != -math.inf else None,
        physical_bytes=physical,
        gb_per_min=physical / 1e9 / (duration / 60) if duration else 0,
    )


def quality_report(stats: dict) -> dict:
    lidar = stats["streams"].get("lidar", {})
    count = lidar.get("count", 0)
    return {
        "lidar_frames": count,
        "lidar_pose_fraction": lidar.get("poses", 0) / count if count else None,
        "lidar_gaps_over_1s": lidar.get("gaps_over_1s", 0),
        "duration_s": stats["duration"],
        "coverage_percent": None,
        "absolute_accuracy_m": None,
        "loop_closures": None,
        "assessment": "Data available for inspection" if count else "No LiDAR",
        "limitations": [
            "Total coverage requires a reference for the boundaries of the space.",
            "Absolute accuracy requires an external reference.",
            "An exported map does not guarantee relocalization after robot restarts.",
        ],
    }
