from __future__ import annotations
"""Style Personalisation capability service — per-user writing-voice overlay.

Biases drafted, *user-sent* text toward how that user actually writes. Learns
from writing samples the user uploads (cold-start). From Phase 4, once Gmail
read-back exists, it will also learn from the diff between Owl's draft and what
the user actually sent — not built yet.

Mechanism (distilled profile + exemplars): the Mind distils a user's samples into
a compact, human-readable **style profile** (tone, formality, sentence length,
sign-offs, characteristic phrases); the profile plus a couple of raw **exemplars**
are returned by :func:`style_block` for the composer to inject as one extra
system block, via persona.system_blocks, ONLY on user-sent surfaces (Composer,
Recap, Check-in).

HARD ISOLATION: per-user and private. It NEVER feeds the shared Owl persona, is
never applied to Owl chat or internal analysis, and one user's voice can never
reach another's drafts. The store is a per-user SQLite db beside Phase-1
memory.db (``mind_data()/style.db``). No-op (empty block) until a user has a
profile, so composition simply falls back to Owl's own voice.
"""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from agents.mind import core as mind
from paths import mind_data

DB_PATH = mind_data() / "style.db"

MAX_EXEMPLARS = 2
_MAX_SAMPLES_FOR_DISTIL = 12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_profiles (
  username      TEXT PRIMARY KEY,
  profile       TEXT NOT NULL,
  sample_count  INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS writing_samples (
  id          TEXT PRIMARY KEY,
  username    TEXT NOT NULL,
  text        TEXT NOT NULL,
  source      TEXT NOT NULL DEFAULT 'upload',
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_user ON writing_samples(username, created_at DESC);
"""

_DISTIL_SYSTEM = """You analyse a person's own writing and produce a compact, reusable STYLE PROFILE \
that another writer could follow to sound like them. British English.

Describe only HOW they write, never WHAT they write about:
- tone and register (formal/casual, warm/direct)
- typical sentence and paragraph length; rhythm
- greetings and sign-offs they use
- characteristic phrases, punctuation and formatting habits
- anything distinctive (emoji, humour, hedging)

Output a short bulleted description, 120 words maximum. No preamble."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Fresh row-factory connection per call; commit on success, always close."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


init_db()


# --- learning inputs -------------------------------------------------------

def add_sample(username: str, text: str, *, source: str = "upload") -> str:
    """Store one of the user's own writing samples. Returns the sample id."""
    text = (text or "").strip()
    if not text:
        raise ValueError("add_sample: text is required")
    sample_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO writing_samples (id, username, text, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (sample_id, username, text, source, _now()),
        )
    return sample_id


def list_samples(username: str, *, limit: int = _MAX_SAMPLES_FOR_DISTIL) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT text, source, created_at FROM writing_samples "
            "WHERE username = ? ORDER BY created_at DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# --- distillation ----------------------------------------------------------

def distil_profile(username: str) -> Optional[str]:
    """Distil the user's samples into a stored style profile (via the Mind).

    Returns the profile text, or None if the user has no samples yet.
    """
    samples = list_samples(username)
    if not samples:
        return None
    joined = "\n\n---\n\n".join(s["text"] for s in samples)
    result = mind.analyze(
        system=_DISTIL_SYSTEM,
        messages=[{"role": "user", "content": f"Writing samples from this user:\n\n{joined}"}],
        max_tokens=512,
    )
    profile = (result.text or "").strip()
    if not profile:
        return None
    with connect() as conn:
        conn.execute(
            "INSERT INTO voice_profiles (username, profile, sample_count, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET "
            "  profile = excluded.profile, sample_count = excluded.sample_count, updated_at = excluded.updated_at",
            (username, profile, len(samples), _now()),
        )
    return profile


def get_profile(username: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute(
            "SELECT profile FROM voice_profiles WHERE username = ?", (username,)
        ).fetchone()
    return row["profile"] if row else None


# --- the composition overlay ----------------------------------------------

def style_block(username: str, *, max_exemplars: int = MAX_EXEMPLARS) -> str:
    """The per-user overlay system block for composition.

    Returns "" when the user has no profile yet, so the composer falls back to
    Owl's own voice. Injected only on user-sent surfaces; never on Owl chat.
    """
    profile = get_profile(username)
    if not profile:
        return ""
    parts = [
        "USER WRITING STYLE — this message is sent by the user as themselves, so match THEIR voice, "
        "not Owl's. Adapt phrasing, tone, greeting and sign-off to the profile below. Do not change the "
        "facts, the structure of the ask, or the Owl-grounded content — only the voice.",
        profile,
    ]
    exemplars = list_samples(username, limit=max_exemplars)
    if exemplars:
        joined = "\n\n".join(f"Example {i + 1}:\n{e['text']}" for i, e in enumerate(exemplars))
        parts.append("A few of the user's own writing samples for reference:\n\n" + joined)
    return "\n\n".join(parts)
