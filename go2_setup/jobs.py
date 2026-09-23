from pathlib import Path
import os
import signal
import subprocess
import threading
import time

from go2_setup.catalog import Catalog, atomic_json
from go2_setup.config import Settings
from go2_setup.records import inspect_recording, quality_report


class MapJobs:
    def __init__(self, settings: Settings, catalog: Catalog) -> None:
        self.settings = settings
        self.catalog = catalog
        self.lock = threading.RLock()
        self.processes: dict[str, subprocess.Popen] = {}

    def start(self, segment_id: str, voxel: float, pgo: bool) -> dict:
        if voxel not in {0.05, 0.1}:
            raise ValueError("Supported resolution: 0.05 or 0.1 m")
        with self.lock:
            segment = self.catalog.get(segment_id, "segment")
            if segment["status"] == "recording":
                raise ValueError("Save the recording before generating the map")
            stats = inspect_recording(Path(segment["path"]))
            lidar = stats["streams"].get("lidar", {})
            if not lidar.get("count"):
                raise ValueError("The recording has no LiDAR")
            if pgo and lidar.get("poses", 0) < lidar["count"] * 0.8:
                raise ValueError("PGO requires poses for at least 80% of LiDAR clouds")
            if any(j["status"] in {"queued", "running"} for j in self.catalog.list("map")):
                raise ValueError("Map generation is already running")
            job = self.catalog.folder_item(
                "map",
                segment,
                status="queued",
                voxel=voxel,
                pgo=pgo,
                source=segment["path"],
                quality=quality_report(stats),
            )
            threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: dict) -> None:
        folder = Path(job["folder"])
        log_path = folder / "generation.log"
        args = [
            str(self.settings.runtime / ".venv/bin/dimos"),
            "map",
            "global",
            job["source"],
            "--lidar",
            "lidar",
            "--voxel",
            str(job["voxel"]),
            "--device",
            "CPU:0",
            "--export",
            "--no-gui",
        ]
        if job["pgo"]:
            args.append("--pgo")
        try:
            with log_path.open("w") as log:
                with self.lock:
                    if self.catalog.get(job["id"])["status"] == "cancelled":
                        return
                    process = subprocess.Popen(
                        args,
                        cwd=folder,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        env={
                            **os.environ,
                            "OMP_NUM_THREADS": "4",
                            "NUMBA_CACHE_DIR": str(self.settings.root / "numba-cache"),
                        },
                    )
                    self.processes[job["id"]] = process
                    self.catalog.update(
                        job["id"], status="running", started=time.time(), log=str(log_path)
                    )
                code = process.wait()
            with self.lock:
                self.processes.pop(job["id"], None)
                if self.catalog.get(job["id"])["status"] == "cancelled":
                    return
            maps = sorted(folder.glob("*.pc2.lcm"))
            if code or not maps:
                raise RuntimeError(f"Map generator exited with code {code}. Check generation.log.")
            # Rerun conversion is a separate bounded subprocess, after the raw map is saved.
            with log_path.open("a") as log:
                view = subprocess.Popen(
                    [
                        str(self.settings.runtime / ".venv/bin/dimos"),
                        "map",
                        "view",
                        str(maps[0]),
                        "--out",
                        str(folder / "inspection.rrd"),
                    ],
                    cwd=folder,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                with self.lock:
                    self.processes[job["id"]] = view
                    if self.catalog.get(job["id"])["status"] == "cancelled":
                        os.killpg(view.pid, signal.SIGTERM)
                try:
                    view.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    os.killpg(view.pid, signal.SIGKILL)
                    view.wait()
                    raise RuntimeError("Rerun export exceeded 120 seconds")
            with self.lock:
                self.processes.pop(job["id"], None)
                if self.catalog.get(job["id"])["status"] == "cancelled":
                    return
            quality = job["quality"]
            quality["export_bytes"] = maps[0].stat().st_size
            atomic_json(folder / "quality.json", quality)
            self.catalog.update(
                job["id"],
                status="ready",
                ended=time.time(),
                map_path=str(maps[0]),
                rerun_path=str(folder / "inspection.rrd") if view.returncode == 0 else None,
                quality=quality,
            )
            self.catalog.event("map", "Map generated and saved")
        except Exception as error:
            with self.lock:
                self.processes.pop(job["id"], None)
                if self.catalog.get(job["id"])["status"] != "cancelled":
                    self.catalog.update(
                        job["id"], status="failed", ended=time.time(), error=str(error)
                    )

    def cancel(self, ident: str) -> None:
        with self.lock:
            item = self.catalog.get(ident, "map")
            if item["status"] not in {"queued", "running"}:
                raise ValueError("The job has already finished")
            self.catalog.update(ident, status="cancelled", ended=time.time())
            process = self.processes.get(ident)
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)

                def ensure_stopped():
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)

                threading.Thread(target=ensure_stopped, daemon=True).start()

    def close(self) -> None:
        for ident in list(self.processes):
            self.cancel(ident)
