from __future__ import annotations
"""Generic per-user JSON-list storage for Cadence agents.

Extracts the load / get / upsert / patch / delete pattern the Lead and
High-Intent agents use by hand, so new agents don't re-implement it. Records are
dicts carrying `id`, `created_at`, `updated_at`, and — when scoped — `username`.
Stored newest-first and capped.

Concurrency: each write is atomic (written to a temp file, then `os.replace`d),
so a reader never sees a half-written file. Concurrent *upserts* to the same
collection are still last-writer-wins — `load → mutate → write` is not locked.
That's acceptable for the low-concurrency, single-operator use this is built for;
a multi-writer deployment should add a file lock (or move that collection to
SQLite, as the Owl agent does).
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def now_label() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M")


def new_id() -> str:
    return uuid.uuid4().hex


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        # Unreadable/corrupt file — fall back to the default rather than crash.
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)  # atomic on POSIX/Windows — no torn reads


class JsonCollection:
    """A capped, newest-first list of dict records persisted to one JSON file.

    `data_dir` is the agent's data directory; `name` the file stem. Passing
    `sandbox=True` to any method routes reads/writes to `data_dir/_sandbox/`,
    matching the rest of the platform's sandbox convention.
    """

    def __init__(self, data_dir: Path, name: str, cap: int = 200):
        self.data_dir = data_dir
        self.name = name
        self.cap = cap

    def _file(self, sandbox: bool) -> Path:
        base = self.data_dir / "_sandbox" if sandbox else self.data_dir
        return base / f"{self.name}.json"

    def load(self, sandbox: bool = False) -> list[dict]:
        return read_json(self._file(sandbox), [])

    def load_user(self, username: str, sandbox: bool = False) -> list[dict]:
        return [r for r in self.load(sandbox) if r.get("username") == username]

    def get(self, record_id: str, username: Optional[str] = None, sandbox: bool = False) -> Optional[dict]:
        for r in self.load(sandbox):
            if r.get("id") != record_id:
                continue
            if username is not None and r.get("username") != username:
                return None
            return r
        return None

    def upsert(self, record: dict, username: Optional[str] = None, sandbox: bool = False) -> dict:
        """Insert or update by id. Newest first. Caps the list."""
        if not record.get("id"):
            record["id"] = new_id()
        if not record.get("created_at"):
            record["created_at"] = now_label()
        record["updated_at"] = now_label()
        if username is not None:
            record["username"] = username

        records = self.load(sandbox)
        records = [r for r in records if r.get("id") != record["id"]]
        records.insert(0, record)
        records = records[: self.cap]
        write_json(self._file(sandbox), records)
        return record

    def patch(self, record_id: str, patch: dict, username: Optional[str] = None, sandbox: bool = False) -> Optional[dict]:
        existing = self.get(record_id, username=username, sandbox=sandbox)
        if not existing:
            return None
        existing.update(patch)
        return self.upsert(existing, sandbox=sandbox)

    def delete(self, record_id: str, username: Optional[str] = None, sandbox: bool = False) -> bool:
        records = self.load(sandbox)
        kept = [
            r for r in records
            if not (r.get("id") == record_id and (username is None or r.get("username") == username))
        ]
        if len(kept) == len(records):
            return False
        write_json(self._file(sandbox), kept)
        return True
