"""SQLite connection and schema for the events record.

Its own file under ``events_data()``, following ``agents/owl/db.py``: a fresh
connection per call, because sqlite3 connections are not safe across threads and
FastAPI runs sync routes in a threadpool; WAL plus a busy timeout so a reader and
the occasional writer coexist.

Four tables, and the shape is the point. A **series** is the show itself, the
thing that comes round every year. An **event** is one year's edition of it,
which is what carries dates, costs and a decision. **Registrations** are the
people, one row each. **Material** hangs off either an event or a person — a
banner belongs to the stand, business cards belong to whoever is handing them
out — which is why ``registration_id`` is nullable and not part of the key.

Cloning an edition into next year is therefore a copy within a series, and the
reason the vault's four-event calendar stops being something a person has to
remember.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from paths import events_data

DATA_DIR = events_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: Path = DATA_DIR / "events.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_series (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  organiser     TEXT NOT NULL DEFAULT '',
  note          TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_series_name ON event_series(name);

-- One year's edition. `status` is the approval gate: an employee's interest
-- lands as `proposed` and only an admin moves it on, so the table never mixes
-- what somebody fancies with what Acme has committed to.
CREATE TABLE IF NOT EXISTS events (
  id                  TEXT PRIMARY KEY,
  series_id           TEXT NOT NULL REFERENCES event_series(id) ON DELETE CASCADE,
  name                TEXT NOT NULL,
  year                INTEGER NOT NULL,
  location            TEXT NOT NULL DEFAULT '',
  country             TEXT NOT NULL DEFAULT '',
  starts_on           TEXT NOT NULL,
  ends_on             TEXT NOT NULL,
  website             TEXT NOT NULL DEFAULT '',
  status              TEXT NOT NULL DEFAULT 'proposed',
  invited             INTEGER NOT NULL DEFAULT 0,
  exhibiting          INTEGER NOT NULL DEFAULT 0,
  demo_required       INTEGER NOT NULL DEFAULT 0,
  demo_type           TEXT NOT NULL DEFAULT '',
  submission_deadline TEXT,
  submission_note     TEXT NOT NULL DEFAULT '',
  exhibit_cost        REAL,
  exhibit_currency    TEXT NOT NULL DEFAULT 'GBP',
  quote_contact_name  TEXT NOT NULL DEFAULT '',
  quote_contact_email TEXT NOT NULL DEFAULT '',
  decision_note       TEXT NOT NULL DEFAULT '',
  decided_by          TEXT,
  decided_at          TEXT,
  created_by          TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  deleted_at          TEXT
);

-- One *live* edition per series per year. The uniqueness is what lets a second
-- person registering interest join the existing record instead of forking it.
--
-- Partial, on `deleted_at IS NULL`: a deleted show must stop occupying its slot.
-- Without the clause, deleting a show and re-adding it — the likeliest thing
-- anybody does after deleting a mistake — fails on the constraint, and the
-- route's ValueError boundary does not catch an IntegrityError.
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_series_year
  ON events(series_id, year) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_event_when
  ON events(deleted_at, starts_on);

CREATE TABLE IF NOT EXISTS registrations (
  id              TEXT PRIMARY KEY,
  event_id        TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  username        TEXT NOT NULL,
  intent          TEXT NOT NULL DEFAULT 'attending',
  needs_travel    INTEGER NOT NULL DEFAULT 0,
  travel_note     TEXT NOT NULL DEFAULT '',
  -- What this person asked for, in their own answer rather than inferred from
  -- the show's flags. `material_items` and `travel_legs` are JSON lists, which
  -- is the one place this schema stores structure in a cell: they are read and
  -- written whole, never queried into, so a table each would buy nothing.
  needs_material  INTEGER NOT NULL DEFAULT 0,
  material_items  TEXT NOT NULL DEFAULT '',
  material_note   TEXT NOT NULL DEFAULT '',
  travel_legs     TEXT NOT NULL DEFAULT '',
  ticket_cost     REAL,
  ticket_currency TEXT NOT NULL DEFAULT 'GBP',
  note            TEXT NOT NULL DEFAULT '',
  status          TEXT NOT NULL DEFAULT 'proposed',
  decided_by      TEXT,
  decided_at      TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reg_event_user
  ON registrations(event_id, username);

-- The checklist: everything a show needs doing, raised on approval from
-- `checklist.CHECKLIST` — the playbook's own timeline.
--
-- **There is no `state` column, and its absence is the design.** Whether a line
-- is done lives in the shared spreadsheet, where the people doing the work
-- already are; Cadence raises the line, computes when it is owed, and reads back
-- only how many remain. Adding a state here would be a second answer to a
-- question the sheet already answers.
--
-- `registration_id` NULL means the line belongs to the show rather than to a
-- person — a stand needs a banner, a person needs cards. Deleting a registration
-- takes that person's lines with it and must never take the show's, hence the
-- cascade on the event only.
CREATE TABLE IF NOT EXISTS checklist_items (
  id              TEXT PRIMARY KEY,
  event_id        TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  registration_id TEXT REFERENCES registrations(id) ON DELETE CASCADE,
  phase           TEXT NOT NULL,
  item            TEXT NOT NULL,
  owner           TEXT NOT NULL DEFAULT '',
  due_on          TEXT NOT NULL,
  created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checklist_event
  ON checklist_items(event_id, due_on);

-- What the spreadsheet last reported back: how many lines a show still owes.
-- Cached rather than asked for on every read — the sheet is a network call and
-- the calendar renders on every page load.
CREATE TABLE IF NOT EXISTS sheet_state (
  event_id    TEXT PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
  outstanding INTEGER NOT NULL DEFAULT 0,
  next_due    TEXT,
  checked_at  TEXT NOT NULL
);
"""

# Columns added to `events` after the table shipped. SQLite has no
# ADD COLUMN IF NOT EXISTS, so they are applied by inspecting the table — the
# first databases were created before the registration form asked for the case
# or the decide-by date, and a `CREATE TABLE IF NOT EXISTS` will not add them.
#
# Nullable only, so existing rows keep their meaning: an event registered before
# these existed simply has no recorded case, which is true.
#: Added to `registrations` after it shipped. Same rule as the events map: a
#: default rather than NOT NULL, so an existing row is valid the moment it lands.
_REGISTRATION_COLUMNS = {
    "needs_material": "INTEGER NOT NULL DEFAULT 0",
    "material_items": "TEXT NOT NULL DEFAULT ''",
    "material_note": "TEXT NOT NULL DEFAULT ''",
    "travel_legs": "TEXT NOT NULL DEFAULT ''",
}

_EVENT_COLUMNS = {
    "rationale": "TEXT",
    "decide_by": "TEXT",
}


#: Indexes that changed shape after they shipped. `CREATE ... IF NOT EXISTS`
#: leaves an existing index of the same name alone however its definition has
#: moved, so a changed index has to be dropped by name and rebuilt. Runs on every
#: start and is idempotent, like everything else in `init_db`.
_INDEXES = """
DROP INDEX IF EXISTS idx_event_series_year;
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_series_year
  ON events(series_id, year) WHERE deleted_at IS NULL;
"""


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
        _add_missing_columns(conn, "events", _EVENT_COLUMNS)
        _add_missing_columns(conn, "registrations", _REGISTRATION_COLUMNS)
        conn.executescript(_INDEXES)
        conn.commit()
    finally:
        conn.close()


init_db()
