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
"""


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
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


init_db()
