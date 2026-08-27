"""Owl Core per-user working memory.

The layer that makes Owl a brain rather than a stateless gateway: it persists,
per user, the preferences / ongoing context / accounts / deals the user is
working, and renders a compact block that is injected proactively into Owl's
system tail (see agents/mind/persona.system_blocks — the block rides the
UNCACHED tail so it never invalidates the cached persona+vault prefix).

Accounts and deals are first-class. Deals are populated by the HubSpot connector
(Phase 4); the schema and read path exist now so the model is ready. The payoff
is vertical-aware cross-referencing: `topics_for_vertical` surfaces what has
resonated on similar-vertical accounts so Owl can support the user across a
vertical, not just the account in front of them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agents.mind import memory_db

# Canon verticals (mirror the brain's gtm verticals); anything else → "other".
VERTICALS = ("finance", "defence", "telecom", "broadcast", "private-5g", "other")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vertical(v: str | None) -> str:
    v = (v or "other").strip().lower()
    return v if v in VERTICALS else "other"


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
def remember_preference(username: str, key: str, value: str) -> None:
    with memory_db.connect() as conn:
        conn.execute(
            """INSERT INTO preferences (username, key, value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(username, key) DO UPDATE SET
                 value = excluded.value, updated_at = excluded.updated_at""",
            (username, key, value, _now()),
        )


def get_preferences(username: str) -> dict[str, str]:
    with memory_db.connect() as conn:
        rows = conn.execute(
            "SELECT key, value FROM preferences WHERE username = ? ORDER BY key",
            (username,),
        ).fetchall()
    return {r["key"]: r["value"] for r in rows}


# --------------------------------------------------------------------------- #
# Context notes
# --------------------------------------------------------------------------- #
def add_context_note(username: str, text: str) -> int:
    with memory_db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO context_notes (username, text, created_at) VALUES (?, ?, ?)",
            (username, text, _now()),
        )
        return int(cur.lastrowid)


def list_context_notes(username: str, limit: int = 10) -> list[dict]:
    with memory_db.connect() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM context_notes WHERE username = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def upsert_account(
    username: str,
    name: str,
    *,
    vertical: str = "other",
    status: str = "active",
    notes: str = "",
    source: str = "manual",
) -> str:
    """Insert or update an account (deduped by (username, name)); return its id."""
    now = _now()
    with memory_db.connect() as conn:
        conn.execute(
            """INSERT INTO accounts (id, username, name, vertical, status, notes, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(username, name) DO UPDATE SET
                 vertical = excluded.vertical, status = excluded.status,
                 notes = excluded.notes, source = excluded.source,
                 updated_at = excluded.updated_at""",
            (uuid.uuid4().hex, username, name, _vertical(vertical), status, notes, source, now, now),
        )
        row = conn.execute(
            "SELECT id FROM accounts WHERE username = ? AND name = ?", (username, name)
        ).fetchone()
    return row["id"]


def list_accounts(username: str, *, status: str | None = "active") -> list[dict]:
    query = "SELECT * FROM accounts WHERE username = ?"
    params: list = [username]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC"
    with memory_db.connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_account(username: str, name: str) -> dict | None:
    with memory_db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE username = ? AND name = ?", (username, name)
        ).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# Deals (schema + read path now; populated via HubSpot connector in Phase 4)
# --------------------------------------------------------------------------- #
def upsert_deal(
    username: str,
    name: str,
    *,
    account_id: str | None = None,
    stage: str = "",
    value: float | None = None,
    close_date: str | None = None,
    source: str = "manual",
    deal_id: str | None = None,
) -> str:
    now = _now()
    did = deal_id or uuid.uuid4().hex
    with memory_db.connect() as conn:
        conn.execute(
            """INSERT INTO deals (id, username, account_id, name, stage, value, close_date, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 account_id = excluded.account_id, name = excluded.name,
                 stage = excluded.stage, value = excluded.value,
                 close_date = excluded.close_date, source = excluded.source,
                 updated_at = excluded.updated_at""",
            (did, username, account_id, name, stage, value, close_date, source, now, now),
        )
    return did


def list_deals(username: str, *, account_id: str | None = None) -> list[dict]:
    query = "SELECT * FROM deals WHERE username = ?"
    params: list = [username]
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    query += " ORDER BY updated_at DESC"
    with memory_db.connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


# --------------------------------------------------------------------------- #
# Account topics (substrate for vertical cross-referencing)
# --------------------------------------------------------------------------- #
def record_account_topic(
    username: str, account_id: str, topic: str, *, vertical: str = "other", signal: str = ""
) -> None:
    with memory_db.connect() as conn:
        conn.execute(
            """INSERT INTO account_topics (username, account_id, vertical, topic, signal, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, account_id, _vertical(vertical), topic, signal, _now()),
        )


def topics_for_vertical(
    username: str, vertical: str, *, exclude_account_id: str | None = None, limit: int = 8
) -> list[str]:
    """Distinct topics that have resonated across the user's accounts in a vertical."""
    query = (
        "SELECT topic, COUNT(*) AS n FROM account_topics "
        "WHERE username = ? AND vertical = ?"
    )
    params: list = [username, _vertical(vertical)]
    if exclude_account_id is not None:
        query += " AND (account_id IS NULL OR account_id != ?)"
        params.append(exclude_account_id)
    query += " GROUP BY topic ORDER BY n DESC, MAX(created_at) DESC LIMIT ?"
    params.append(limit)
    with memory_db.connect() as conn:
        return [r["topic"] for r in conn.execute(query, params).fetchall()]


# --------------------------------------------------------------------------- #
# Aggregate read + proactive render
# --------------------------------------------------------------------------- #
def load_user_memory(username: str) -> dict:
    return {
        "preferences": get_preferences(username),
        "context_notes": list_context_notes(username),
        "accounts": list_accounts(username),
        "deals": list_deals(username),
    }


def render_memory_block(username: str, *, active_vertical: str | None = None) -> str:
    """Render the compact proactive memory block for Owl's system tail.

    Returns "" when the user has no memory yet (so the tail stays clean).
    """
    mem = load_user_memory(username)
    lines: list[str] = []

    prefs = mem["preferences"]
    if prefs:
        lines.append("Preferences: " + "; ".join(f"{k}={v}" for k, v in prefs.items()))

    accounts = mem["accounts"]
    if accounts:
        lines.append(
            "Active accounts: "
            + "; ".join(f"{a['name']} ({a['vertical']})" for a in accounts[:12])
        )

    deals = mem["deals"]
    if deals:
        lines.append(
            "Open deals: "
            + "; ".join(
                f"{d['name']}" + (f" — {d['stage']}" if d["stage"] else "") for d in deals[:12]
            )
        )

    notes = mem["context_notes"]
    if notes:
        lines.append("Recent context:")
        lines.extend(f"- {n['text']}" for n in notes[:5])

    # Vertical cross-reference: use the given vertical, else the user's dominant
    # active vertical, so Owl surfaces what has resonated across similar accounts.
    cross_vertical = _vertical(active_vertical) if active_vertical else _dominant_vertical(accounts)
    if cross_vertical:
        topics = topics_for_vertical(username, cross_vertical)
        if topics:
            lines.append(
                f"Cross-reference — topics that have landed on other "
                f"{cross_vertical} accounts: " + ", ".join(topics)
            )

    if not lines:
        return ""
    return "# Working memory for this user (use it proactively)\n" + "\n".join(lines)


def _dominant_vertical(accounts: list[dict]) -> str | None:
    """The most common non-'other' vertical across the user's active accounts."""
    counts: dict[str, int] = {}
    for a in accounts:
        v = a.get("vertical", "other")
        if v and v != "other":
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def promote_insight_to_vault(
    username: str,
    *,
    title: str,
    description: str,
    content: str,
    topic: str = "",
    session_id: str = "",
    suggested_source: str = "owl-memory",
) -> "object":
    """Propose a durable memory insight for team-wide knowledge through the
    EXISTING added-knowledge gate (writes to added/pending → admin approves).
    Reuses vault.write_added_knowledge — no new gate is built here.
    """
    from agents.shared import vault  # lazy: platform layer must not import at load

    return vault.write_added_knowledge(
        title=title,
        description=description,
        content=content,
        topic=topic,
        what_owl_said="",
        user_correction=content,
        submitted_by=username,
        session_id=session_id,
        suggested_source=suggested_source,
    )
