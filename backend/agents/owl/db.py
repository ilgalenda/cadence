"""SQLite connection and schema for Owl conversations.

One database file lives under ``owl_data()`` (routed through ``paths.py``).
We open a fresh connection per call — sqlite3 connections are not safe to
share across threads, and FastAPI runs sync routes in a threadpool. WAL mode
plus a busy timeout lets concurrent readers and the occasional writer coexist
without the read-modify-write races the old shared JSON file suffered.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from paths import owl_data

DATA_DIR = owl_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: Path = DATA_DIR / "owl.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL,
  title         TEXT NOT NULL DEFAULT 'Chat',
  model_used    TEXT,
  topics        TEXT NOT NULL DEFAULT '[]',
  pending_correction_draft TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_conv_user_updated
  ON conversations(username, deleted_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL,
  content         TEXT NOT NULL,
  seq             INTEGER NOT NULL,
  created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, seq);

-- Organisation. A project is the top-level container and carries standing
-- instructions that ride into every conversation filed under it. Folders nest
-- inside a project; conversations sit either in a folder, at a project's root,
-- or unfiled.
CREATE TABLE IF NOT EXISTS projects (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL,
  name          TEXT NOT NULL,
  instructions  TEXT NOT NULL DEFAULT '',
  position      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  archived_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_project_user
  ON projects(username, archived_at, position);

CREATE TABLE IF NOT EXISTS folders (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  username    TEXT NOT NULL,
  name        TEXT NOT NULL,
  parent_id   TEXT REFERENCES folders(id) ON DELETE CASCADE,
  position    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_folder_project
  ON folders(project_id, parent_id, position);
"""

# Columns added to `conversations` after the table shipped. SQLite has no
# ADD COLUMN IF NOT EXISTS, so they are applied by inspecting the table.
#
# Deliberately NOT foreign keys: a conversation outlives its container. Deleting
# a project unfiles its conversations rather than destroying them, which a
# cascading FK would make impossible to express.
_CONVERSATION_COLUMNS = {
    "project_id":  "TEXT",
    "folder_id":   "TEXT",
    "pinned_at":   "TEXT",
    "archived_at": "TEXT",
}

_CONVERSATION_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_conv_project
  ON conversations(username, project_id, folder_id, deleted_at);
"""


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add any of ``columns`` the table does not already have.

    Idempotent, so it is safe to run on every start. Only ever adds nullable
    columns — existing rows keep their meaning and simply read as NULL, which is
    exactly 'unfiled, unpinned, not archived'.
    """
    present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns.items():
        if name not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Yield a row-factory connection, committing on success and always closing."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        _add_missing_columns(conn, "conversations", _CONVERSATION_COLUMNS)
        conn.executescript(_CONVERSATION_INDEXES)
        conn.commit()
    finally:
        conn.close()


init_db()
