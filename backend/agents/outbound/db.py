"""SQLite connection and schema for the outbound tracker.

Its own file under ``outbound_data()``, following ``agents/events/db.py``: a fresh
connection per call, because sqlite3 connections are not safe across threads and
FastAPI runs sync routes in a threadpool; WAL plus a busy timeout so a reader and
the occasional writer coexist.

Three tables, and the shape is the point. A **tracker** is one campaign's account
list and the goals it is measured against. A **row** is one account on it, carrying
what the agent proposed and what the deal is made of. **Events** are what has
actually happened to a row — a touch fired, a status moved — and they are appended,
never rewritten.

That third table is the reason this is SQLite rather than a JSON blob. The published
artefact this replaces records a touch as ``1`` in an array, which cannot say *when*
it happened or *who* fired it, and a status that moves from ``sequencing`` to
``dead`` overwrites the fact that it was ever in sequence. A tracker is the safety
mechanism for a manual sequence — suppression depends on knowing what was already
sent — so the trail is the feature and the row's ``status`` is only its projection.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from paths import outbound_data

DATA_DIR = outbound_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: Path = DATA_DIR / "outbound.db"

_SCHEMA = """
-- One campaign's account list. The goals live here rather than in the page so a
-- second tracker can be measured against different ones without editing code.
CREATE TABLE IF NOT EXISTS trackers (
  id                TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  username          TEXT NOT NULL,
  goal_gbp          INTEGER NOT NULL DEFAULT 0,
  target_touches    INTEGER NOT NULL DEFAULT 0,
  target_replies    INTEGER NOT NULL DEFAULT 0,
  target_calls      INTEGER NOT NULL DEFAULT 0,
  target_qualified  INTEGER NOT NULL DEFAULT 0,
  artifact_url      TEXT NOT NULL DEFAULT '',
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

-- One account. Everything above `procurement_route` is what the agent proposed;
-- everything below it is what a person has since decided. `value_est_gbp` is
-- nullable on purpose: NULL means unpriced, and 0 would mean worthless.
CREATE TABLE IF NOT EXISTS tracker_rows (
  id                  TEXT PRIMARY KEY,
  tracker_id          TEXT NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
  account             TEXT NOT NULL,
  domain              TEXT NOT NULL DEFAULT '',
  segment             TEXT NOT NULL DEFAULT '',
  tier                INTEGER NOT NULL DEFAULT 1,
  campaign            TEXT NOT NULL DEFAULT '',
  trigger_text        TEXT NOT NULL DEFAULT '',
  trigger_source      TEXT NOT NULL DEFAULT '',
  geography           TEXT NOT NULL DEFAULT '',
  target_roles        TEXT NOT NULL DEFAULT '',
  confidence          TEXT NOT NULL DEFAULT 'medium',
  deal_lines          TEXT NOT NULL DEFAULT '[]',
  attach_support      INTEGER NOT NULL DEFAULT 0,
  fleet_insight_units  INTEGER NOT NULL DEFAULT 0,
  value_est_gbp       INTEGER,
  value_note          TEXT NOT NULL DEFAULT '',
  notes               TEXT NOT NULL DEFAULT '',
  procurement_route   TEXT NOT NULL DEFAULT '',
  status              TEXT NOT NULL DEFAULT 'not_started',
  next_due            TEXT NOT NULL DEFAULT '',
  created_at          TEXT NOT NULL
);

-- Append-only. A touch fired and a status moved are facts that happened, so they
-- are added, never edited. Undoing a touch appends its own event rather than
-- deleting one, because "this was sent and then retracted" and "this was never
-- sent" are different things to somebody deciding whether to send the next one.
CREATE TABLE IF NOT EXISTS tracker_events (
  id           TEXT PRIMARY KEY,
  row_id       TEXT NOT NULL REFERENCES tracker_rows(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL,
  touch_index  INTEGER,
  from_value   TEXT NOT NULL DEFAULT '',
  to_value     TEXT NOT NULL DEFAULT '',
  actor        TEXT NOT NULL,
  source       TEXT NOT NULL DEFAULT '',
  at           TEXT NOT NULL
);
"""

_INDEXES = """
-- One row per account per tracker. A second proposal naming an account already on
-- the list must join it, not fork it — the same rule the events record needed.
CREATE UNIQUE INDEX IF NOT EXISTS idx_row_account ON tracker_rows(tracker_id, account);
CREATE INDEX IF NOT EXISTS idx_row_tracker ON tracker_rows(tracker_id);
CREATE INDEX IF NOT EXISTS idx_event_row ON tracker_events(row_id, at);
CREATE INDEX IF NOT EXISTS idx_tracker_user ON trackers(username);
"""

#: Columns added after the first release. Declared here so an existing database
#: gains them on start rather than needing a migration script.
_TRACKER_COLUMNS: dict[str, str] = {}
_ROW_COLUMNS: dict[str, str] = {}
_EVENT_COLUMNS: dict[str, str] = {}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add any of ``columns`` the table does not already have.

    Idempotent, so it is safe to run on every start.
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
        _add_missing_columns(conn, "trackers", _TRACKER_COLUMNS)
        _add_missing_columns(conn, "tracker_rows", _ROW_COLUMNS)
        _add_missing_columns(conn, "tracker_events", _EVENT_COLUMNS)
        conn.executescript(_INDEXES)
        conn.commit()
    finally:
        conn.close()


init_db()
