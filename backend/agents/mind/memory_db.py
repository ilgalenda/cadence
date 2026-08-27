"""SQLite connection and schema for Owl Core per-user working memory.

One database under ``mind_data()`` (routed through ``paths.py``), following the
same discipline as ``agents/owl/db.py``: a fresh connection per call (sqlite3
connections aren't thread-safe and FastAPI runs sync routes in a threadpool),
WAL mode, and a busy timeout so concurrent readers and the occasional writer
coexist without the read-modify-write races the shared-JSON stores suffer.

All rows are keyed by ``username``. This is the substrate for Phase 1 Memory:
preferences, ongoing-context notes, accounts, deals, and per-account topics
(the material for vertical cross-referencing).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from paths import mind_data

DATA_DIR = mind_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Module-level so tests can point it at a tmp file (monkeypatch + init_db()).
DB_PATH = DATA_DIR / "memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
  username    TEXT NOT NULL,
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (username, key)
);

CREATE TABLE IF NOT EXISTS context_notes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  username    TEXT NOT NULL,
  text        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON context_notes(username, created_at DESC);

CREATE TABLE IF NOT EXISTS accounts (
  id          TEXT PRIMARY KEY,
  username    TEXT NOT NULL,
  name        TEXT NOT NULL,
  vertical    TEXT NOT NULL DEFAULT 'other',
  status      TEXT NOT NULL DEFAULT 'active',
  notes       TEXT NOT NULL DEFAULT '',
  source      TEXT NOT NULL DEFAULT 'manual',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_user_name ON accounts(username, name);
CREATE INDEX IF NOT EXISTS idx_accounts_user_updated ON accounts(username, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_user_vertical ON accounts(username, vertical);

CREATE TABLE IF NOT EXISTS deals (
  id          TEXT PRIMARY KEY,
  username    TEXT NOT NULL,
  account_id  TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  stage       TEXT NOT NULL DEFAULT '',
  value       REAL,
  close_date  TEXT,
  source      TEXT NOT NULL DEFAULT 'manual',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_user ON deals(username, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_deals_account ON deals(account_id);

CREATE TABLE IF NOT EXISTS account_topics (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  username    TEXT NOT NULL,
  account_id  TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  vertical    TEXT NOT NULL DEFAULT 'other',
  topic       TEXT NOT NULL,
  signal      TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_user_vertical ON account_topics(username, vertical);
CREATE INDEX IF NOT EXISTS idx_topics_account ON account_topics(account_id);
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
