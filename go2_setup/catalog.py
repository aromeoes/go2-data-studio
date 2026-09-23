from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json
import os
import tempfile
import sqlite3
import time
import uuid

from go2_setup.config import MAIN_SHA


def identifier() -> str:
    return uuid.uuid4().hex[:16]


def atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False) as out:
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.flush()
        os.fsync(out.fileno())
        temporary = Path(out.name)
    temporary.replace(path)


class Catalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent TEXT,
                    created REAL NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS object_parent ON objects(parent,kind);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, ts REAL, kind TEXT, message TEXT);
            """)
        for job in self.list("map"):
            if job["status"] in {"queued", "running"}:
                self.update(
                    job["id"],
                    status="interrupted",
                    error="The app restarted during map generation.",
                )
        for session in self.list("session"):
            if session["status"] == "recording":
                self.update(session["id"], status="interrupted", ended=time.time())
        for segment in self.list("segment"):
            if segment["status"] == "recording":
                self.update(segment["id"], status="interrupted", ended=time.time())

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "catalog.sqlite", timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def create(self, kind: str, parent: str | None = None, **data) -> dict:
        item = {
            "id": identifier(),
            "kind": kind,
            "parent": parent,
            "created": time.time(),
            "dimos_sha": MAIN_SHA,
            **data,
        }
        with self.db() as db:
            db.execute(
                "INSERT INTO objects VALUES (?,?,?,?,?)",
                (item["id"], kind, parent, item["created"], json.dumps(item)),
            )
        return item

    def get(self, ident: str, kind: str | None = None) -> dict:
        with self.db() as db:
            row = db.execute("SELECT data FROM objects WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError("Item not found")
        item = json.loads(row[0])
        if kind and item["kind"] != kind:
            raise ValueError("Incorrect item type")
        return item

    def update(self, ident: str, **changes) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM objects WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise KeyError(ident)
            item = {**json.loads(row[0]), **changes}
            db.execute("UPDATE objects SET data=? WHERE id=?", (json.dumps(item), ident))
        if item.get("folder"):
            atomic_json(Path(item["folder"]) / "manifest.json", item)
        return item

    def list(self, kind: str, parent: str | None = None) -> list[dict]:
        with self.db() as db:
            if parent:
                rows = db.execute(
                    "SELECT data FROM objects WHERE kind=? AND parent=? ORDER BY created DESC",
                    (kind, parent),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT data FROM objects WHERE kind=? ORDER BY created DESC", (kind,)
                ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def event(self, kind: str, message: str) -> None:
        with self.db() as db:
            db.execute(
                "INSERT INTO events(ts,kind,message) VALUES(?,?,?)", (time.time(), kind, message)
            )

    def events(self) -> list[dict]:
        with self.db() as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 30")
            ]

    def space(self, name: str) -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("Name must contain between 1 and 80 characters")
        item = self.create("space", name=name)
        folder = self.root / "spaces" / item["id"]
        folder.mkdir()
        return self.update(item["id"], folder=str(folder))

    def rename_space(self, ident: str, name: str) -> dict:
        self.get(ident, "space")
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("Name must contain between 1 and 80 characters")
        return self.update(ident, name=name)

    def folder_item(self, kind: str, parent: dict, **data) -> dict:
        item = self.create(kind, parent["id"], **data)
        folder = Path(parent["folder"]) / (kind + "s") / item["id"]
        folder.mkdir(parents=True)
        return self.update(item["id"], folder=str(folder))
