from contextlib import asynccontextmanager
from pathlib import Path
import base64
import fcntl
import shutil
import sqlite3
import subprocess
import threading
import time
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from go2_setup.agent import NavigatorAgent
from go2_setup.catalog import Catalog
from go2_setup.cloud import CloudBackups
from go2_setup.english import english
from go2_setup.config import MAIN_SHA, Settings
from go2_setup.jobs import MapJobs
from go2_setup.library import remove_segment
from go2_setup.records import inspect_recording
from go2_setup.supervisor import Supervisor
from go2_setup.sdk_relay import ConsoleRelay
from go2_setup.sdk_control import CommandOwner


class ConnectBody(BaseModel):
    ip: str = ""
    segment_id: str | None = None


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DeleteBody(BaseModel):
    confirmed: bool = False


class ImportBody(BaseModel):
    space_id: str
    path: str


class ModeBody(BaseModel):
    mode: str


class EpochBody(BaseModel):
    epoch: int


class TeleopBody(EpochBody):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(ge=-0.2, le=0.2, allow_inf_nan=False)
    yaw: float = Field(ge=-0.5, le=0.5, allow_inf_nan=False)


class RecordBody(BaseModel):
    space_id: str


class MapBody(BaseModel):
    segment_id: str
    voxel: float = 0.1
    pgo: bool = True


class DisconnectBody(BaseModel):
    parked_confirmed: bool = False


class VisionBody(BaseModel):
    api_key: str = Field(default="", repr=False)
    enabled: bool = True


class TextBody(BaseModel):
    epoch: int
    text: str = Field(min_length=1, max_length=2000)
    space_id: str | None = None


class AgentConfigBody(BaseModel):
    provider: str
    model: str = Field(max_length=160)
    api_key: str = Field(default="", repr=False, max_length=4096)
    base_url: str = Field(default="", max_length=500)
    vision: bool = False


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    settings.initialize()
    catalog = Catalog(settings.root)
    supervisor = Supervisor(settings, catalog)
    relay = ConsoleRelay(settings)
    supervisor.relay = relay
    jobs = MapJobs(settings, catalog)
    agent = NavigatorAgent(supervisor, jobs)
    cloud = CloudBackups(settings, catalog)
    import_lock = threading.Lock()
    command_owner = CommandOwner()

    @asynccontextmanager
    async def lifespan(app):
        try:
            relay.start()
            yield
        finally:
            agent.close()
            cloud.close()
            jobs.close()
            supervisor.close()
            relay.stop()

    app = FastAPI(title="Go2 Space Setup", lifespan=lifespan)
    app.state.supervisor = supervisor
    app.state.catalog = catalog
    app.state.jobs = jobs
    app.state.cloud = cloud
    app.state.agent = agent

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin")
        allowed_origins = {f"http://127.0.0.1:{settings.port}", f"http://localhost:{settings.port}"}
        if host not in {"127.0.0.1", "localhost", "testserver"} or (
            origin and origin not in allowed_origins
        ):
            return JSONResponse({"detail": "Local access only"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and request.headers.get("X-Go2-Request") != "1":
            return JSONResponse(
                {"detail": "Local console request header is missing"}, status_code=403
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; connect-src 'self' http://127.0.0.1:{settings.relay_port} https://127.0.0.1:*; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(KeyError)
    async def key_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.get("/api/state")
    def state():
        return {
            **supervisor.snapshot(),
            "dimos_sha": MAIN_SHA,
            "spaces": catalog.list("space"),
            "sessions": catalog.list("session"),
            "segments": catalog.list("segment"),
            "maps": [{**m, "error": english(m.get("error"))} for m in catalog.list("map")],
            "events": [{**e, "message": english(e["message"])} for e in catalog.events()],
            "cloud": cloud.status(),
            "agent": agent.snapshot(),
        }

    @app.get("/api/sdk")
    def sdk_info(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return relay.info()

    def bridge_only(request):
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + supervisor.token):
            raise HTTPException(403, "Relay bridge authorization required")

    @app.get("/api/sdk/state")
    def sdk_state(request: Request):
        bridge_only(request)
        result = state()
        result["telemetry"] = {
            k: v for k, v in result["telemetry"].items() if k not in {"camera", "map", "pose"}
        }
        return result

    @app.post("/api/sdk/command")
    def sdk_command(request: Request, item: dict):
        bridge_only(request)
        # Do not execute controls delayed by a busy queue or old connection.
        sent = item.get("sent", 0)
        if not isinstance(sent, (int, float)) or not 0 <= time.time() - sent <= 3:
            raise ValueError("Command expired; send it again")
        command_owner.authorize(item)
        path, body = item.get("path"), item.get("body", {})
        if path == "/mode":
            return mode(ModeBody(**body))
        if path == "/heartbeat":
            result = heartbeat(EpochBody(**body))
            if not result.get("ok"):
                with command_owner.lock:
                    if command_owner.client == item["client"]:
                        command_owner.client = None
                        command_owner.deadline = 0
            return result
        if path == "/release":
            return release(EpochBody(**body))
        if path == "/stop":
            return stop()
        if path == "/clear":
            return clear()
        if path in {"/posture/stand", "/posture/lie"}:
            return posture(path.rsplit("/", 1)[1])
        if path == "/agent":
            return instruction(TextBody(**body))
        raise ValueError("Unsupported SDK command")

    @app.post("/api/cloud/login")
    def cloud_login():
        return cloud.begin_login()

    @app.post("/api/cloud/refresh")
    def cloud_refresh():
        return cloud.refresh()

    @app.post("/api/cloud/uploads/{segment_id}")
    def cloud_upload(segment_id: str):
        return cloud.start(segment_id)

    @app.post("/api/cloud/uploads/{segment_id}/pause")
    def cloud_pause(segment_id: str):
        return cloud.pause_upload(segment_id)

    @app.get("/api/camera")
    def camera():
        data = supervisor.telemetry.get("camera")
        if not data:
            raise HTTPException(404, "No camera available")
        return Response(
            base64.b64decode(data), media_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/spaces")
    def create_space(body: NameBody):
        return catalog.space(body.name)

    @app.post("/api/spaces/{ident}/rename")
    def rename_space(ident: str, body: NameBody):
        return catalog.rename_space(ident, body.name)

    @app.post("/api/segments/{ident}/delete")
    def delete_segment(ident: str, body: DeleteBody):
        if not body.confirmed:
            raise ValueError("Confirm permanent deletion of the recording and its generated maps")
        return remove_segment(ident, catalog, supervisor, jobs, cloud)

    @app.post("/api/connect")
    def connect(body: ConnectBody):
        with supervisor.lock:
            replay = None
            if body.segment_id:
                segment = catalog.get(body.segment_id, "segment")
                if segment["status"] in {"recording", "importing"}:
                    raise ValueError("Save the recording before replaying it")
                replay = segment["path"]
            supervisor.connect(body.ip, replay)
        return {"ok": True}

    @app.post("/api/disconnect")
    def disconnect(body: DisconnectBody | None = None):
        with supervisor.lock:
            physical = supervisor.target and not supervisor.target.get("replay")
            if physical and (not body or not body.parked_confirmed):
                raise ValueError(
                    "Before disconnecting, lie Go2 down and visually confirm it is supported"
                )
            if physical and supervisor.mode != "idle":
                raise ValueError("Stop movement before confirming disconnection")
            supervisor.disconnect()
        return {"ok": True}

    @app.post("/api/mode")
    def mode(body: ModeBody):
        agent.cancel()
        return supervisor.change_mode(body.mode)

    @app.post("/api/heartbeat")
    def heartbeat(body: EpochBody):
        if supervisor.connection != "online":
            return {"ok": False}
        return supervisor.call("/heartbeat", body.model_dump(), timeout=2)

    @app.post("/api/teleop")
    def teleop(body: TeleopBody):
        if supervisor.connection != "online":
            raise ValueError("Go2 disconnected")
        return supervisor.call("/teleop", body.model_dump(), timeout=2)

    @app.post("/api/release")
    def release(body: EpochBody):
        if supervisor.connection != "online":
            return {"ok": False}
        return supervisor.call("/release", body.model_dump(), timeout=20)

    @app.post("/api/stop")
    def stop():
        agent.cancel()
        with supervisor.lock:
            if supervisor.connection == "online":
                result = supervisor.call("/halt", {"latch": True}, timeout=20)
                supervisor.mode, supervisor.epoch = "idle", result["epoch"]
            else:
                supervisor.mode = "idle"
                supervisor.epoch += 1
        catalog.event("control", "Stop requested")
        return {"ok": True}

    @app.post("/api/clear")
    def clear():
        return supervisor.call("/clear")

    @app.post("/api/posture/{action}")
    def posture(action: str):
        if supervisor.connection != "online":
            raise ValueError("Go2 disconnected")
        return supervisor.call("/posture", {"action": action}, timeout=20)

    @app.post("/api/record/start")
    def record(body: RecordBody):
        return supervisor.start_recording(body.space_id)

    @app.post("/api/record/stop")
    def finish_record():
        return supervisor.finish_recording()

    @app.post("/api/import")
    def import_recording(body: ImportBody):
        with import_lock:
            source = Path(body.path).expanduser().resolve()
            if source.suffix != ".db" or not source.is_file():
                raise ValueError("Select an existing DimOS .db recording")
            space = catalog.get(body.space_id, "space")
            stats = inspect_recording(source)
            if not stats["streams"].get("lidar", {}).get("count"):
                raise ValueError("The recording has no LiDAR")
            if shutil.disk_usage(settings.root).free < source.stat().st_size + 3e9:
                raise ValueError("Not enough disk space to copy the recording")
            session = catalog.folder_item(
                "session", space, status="closed", source="import", original_path=str(source)
            )
            segment = catalog.folder_item(
                "segment", session, status="importing", frame_epoch="imported"
            )
            target = Path(segment["folder"]) / "raw.db"
            try:
                with (
                    sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src,
                    sqlite3.connect(target) as dst,
                ):
                    src.backup(dst)
                segment = catalog.update(
                    segment["id"],
                    status="closed",
                    path=str(target),
                    stats=inspect_recording(target),
                )
                catalog.event("record", "Recording imported as an independent copy")
                return segment
            except Exception:
                catalog.update(segment["id"], status="failed")
                raise

    @app.post("/api/maps")
    def generate(body: MapBody):
        if supervisor.mode != "idle":
            raise ValueError("Pause movement before generating a map")
        return jobs.start(body.segment_id, body.voxel, body.pgo)

    @app.post("/api/maps/{ident}/cancel")
    def cancel(ident: str):
        jobs.cancel(ident)
        return {"ok": True}

    @app.post("/api/agent/conversation")
    def new_conversation():
        return agent.new_conversation()

    @app.post("/api/agent/cancel")
    def cancel_agent():
        return agent.cancel()

    @app.post("/api/agent/config")
    def configure_agent(body: AgentConfigBody):
        agent.new_conversation()
        return agent.config.configure(**body.model_dump())

    @app.post("/api/agent/vision")
    def configure_vision(body: VisionBody):
        agent.new_conversation()
        result = agent.vision.configure(body.api_key, body.enabled)
        # Backward-compatible endpoint applies the toggle to the current agent.
        cfg = agent.config.resolve()
        agent.config.configure(
            cfg["provider"],
            cfg["model"],
            body.api_key if cfg["provider"] == "openai" else "",
            cfg["base_url"],
            body.enabled,
        )
        return result

    @app.post("/api/agent")
    def instruction(body: TextBody):
        return agent.submit(body.text, body.epoch, body.space_id)

    def artifact(ident, kind):
        item = catalog.get(ident)
        fields = {
            "raw": "path",
            "map": "map_path",
            "rerun": "rerun_path",
            "log": "log",
            "folder": "folder",
        }
        value = item.get(fields.get(kind, ""))
        if not value:
            raise ValueError("The file does not exist yet")
        path = Path(value).resolve()
        if not path.is_relative_to(settings.root.resolve()) or not path.exists():
            raise ValueError("Path not allowed or file missing")
        return path

    @app.get("/api/files/{ident}/{kind}")
    def download(ident: str, kind: str):
        path = artifact(ident, kind)
        if not path.is_file():
            raise ValueError("Not a file")
        return FileResponse(path, filename=path.name)

    @app.post("/api/open/{ident}/{kind}")
    def open_artifact(ident: str, kind: str):
        path = artifact(ident, kind)
        if kind == "rerun":
            subprocess.Popen(
                [str(settings.runtime / ".venv/bin/rerun"), str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            subprocess.run(["open", "-R", str(path)], check=True, timeout=10)
        return {"ok": True}

    web = Path(__file__).resolve().parent.parent / "web/dist"
    if web.exists():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


def main():
    settings = Settings()
    settings.initialize()
    with (settings.root / ".console.lock").open("w") as instance_lock:
        try:
            fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Ya hay una consola usando esta carpeta de datos")
        uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
