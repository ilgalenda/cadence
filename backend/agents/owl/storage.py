"""Owl conversation storage (SQLite-backed).

Every conversation has a stable id. A turn is persisted in two halves:
``append_user_turn`` at stream start (so the id is always backed by a real row
and the user's message survives a failed generation) and ``append_assistant_turn``
once Owl's reply is complete. All reads and writes are scoped by ``username`` so
ownership is enforced at the data layer.

Timestamps are stored ISO8601 (UTC) internally; the list/get endpoints expose
the legacy ``"%d %b %Y, %H:%M"`` display string under the ``timestamp`` key so
the existing frontend time parsers keep working unchanged.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from agents.owl.db import connect

SESSION_CAP = 200
_DISPLAY_FMT = "%d %b %Y, %H:%M"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_timestamp(iso: Optional[str] = None) -> str:
    """Render an ISO8601 timestamp (or now) as the legacy display string."""
    if not iso:
        return datetime.now(timezone.utc).strftime(_DISPLAY_FMT)
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime(_DISPLAY_FMT)
    except (ValueError, TypeError):
        return iso


def _merge_topics(existing: list[str], incoming: list[str], cap: int = 3) -> list[str]:
    merged = list(existing)
    for t in incoming:
        if t not in merged:
            merged.append(t)
    return merged[:cap]


def conversation_exists(conv_id: str, username: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND username = ? AND deleted_at IS NULL",
            (conv_id, username),
        ).fetchone()
        return row is not None


def model_locked_for(conv_id: str, username: str) -> Optional[str]:
    """Return the model already locked to this conversation, if any."""
    with connect() as conn:
        row = conn.execute(
            "SELECT model_used FROM conversations WHERE id = ? AND username = ? AND deleted_at IS NULL",
            (conv_id, username),
        ).fetchone()
        return row["model_used"] if row and row["model_used"] else None


def append_message(conn, conv_id: str, role: str, content: str) -> None:
    """Append one message to a conversation (caller owns the transaction)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), -1) + 1 AS next FROM messages WHERE conversation_id = ?",
        (conv_id,),
    ).fetchone()
    conn.execute(
        """INSERT INTO messages (conversation_id, role, content, seq, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (conv_id, role, content, row["next"], _now_iso()),
    )


def _prune_user(conn, username: str, cap: int = SESSION_CAP) -> None:
    """Hard-delete the user's oldest conversations beyond ``cap`` (messages
    cascade). Called only when a brand-new conversation is created, so the
    on-disk store stays bounded without pruning on every continuation turn."""
    stale = conn.execute(
        """SELECT id FROM conversations WHERE username = ? AND deleted_at IS NULL
           ORDER BY updated_at DESC LIMIT -1 OFFSET ?""",
        (username, cap),
    ).fetchall()
    for r in stale:
        conn.execute("DELETE FROM conversations WHERE id = ?", (r["id"],))


def append_user_turn(
    conv_id: str,
    username: str,
    user_msg: str,
    *,
    title: str,
    model_used: str,
    topics: list[str],
) -> None:
    """Persist the conversation row (creating it on the first turn) and append
    the user message.

    Called at stream *start* so the conversation id the client receives is
    always backed by a real row, and the user's message is never lost even if
    generation errors or returns empty. The title and model are locked on the
    first turn.
    """
    now = _now_iso()
    with connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND username = ?",
            (conv_id, username),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO conversations
                   (id, username, title, model_used, topics, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (conv_id, username, title or "Chat", model_used,
                 json.dumps(topics[:3]), now, now),
            )
            _prune_user(conn, username)
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND username = ?",
                (now, conv_id, username),
            )
        append_message(conn, conv_id, "user", user_msg)


def append_assistant_turn(
    conv_id: str,
    username: str,
    assistant_msg: str,
    *,
    model_used: str,
    topics: list[str],
    pending_correction_draft: Optional[dict] = None,
) -> None:
    """Append Owl's reply to an existing conversation, merge topics, store the
    latest correction draft, and bump ``updated_at``. No-op if the conversation
    row is missing (the user turn always precedes this call)."""
    now = _now_iso()
    draft_json = json.dumps(pending_correction_draft) if pending_correction_draft else None
    with connect() as conn:
        existing = conn.execute(
            "SELECT topics FROM conversations WHERE id = ? AND username = ?",
            (conv_id, username),
        ).fetchone()
        if existing is None:
            return
        try:
            current = json.loads(existing["topics"]) or []
        except (json.JSONDecodeError, TypeError):
            current = []
        conn.execute(
            """UPDATE conversations
               SET topics = ?, model_used = COALESCE(model_used, ?),
                   pending_correction_draft = ?, updated_at = ?
               WHERE id = ? AND username = ?""",
            (json.dumps(_merge_topics(current, topics)), model_used,
             draft_json, now, conv_id, username),
        )
        append_message(conn, conv_id, "assistant", assistant_msg)


def _row_to_summary(row) -> dict:
    try:
        topics = json.loads(row["topics"]) or []
    except (json.JSONDecodeError, TypeError):
        topics = []
    return {
        "id": row["id"],
        "title": row["title"],
        "type": "chat",
        "model_used": row["model_used"] or "owl",
        "topics": topics,
        "timestamp": format_timestamp(row["updated_at"]),
        "ts": row["updated_at"],
    }


def list_conversations(
    username: str,
    query: Optional[str] = None,
    limit: int = SESSION_CAP,
) -> list[dict]:
    """Newest-first summaries (no message bodies) for a user, optional search."""
    with connect() as conn:
        if query:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT * FROM conversations
                   WHERE username = ? AND deleted_at IS NULL
                     AND (title LIKE ? OR id IN (
                       SELECT conversation_id FROM messages WHERE content LIKE ?))
                   ORDER BY updated_at DESC LIMIT ?""",
                (username, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM conversations
                   WHERE username = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (username, limit),
            ).fetchall()
        return [_row_to_summary(r) for r in rows]


def get_conversation(conv_id: str, username: str) -> Optional[dict]:
    """Full conversation with ordered messages, or None if absent/not owned."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND username = ? AND deleted_at IS NULL",
            (conv_id, username),
        ).fetchone()
        if row is None:
            return None
        msgs = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY seq",
            (conv_id,),
        ).fetchall()
        try:
            topics = json.loads(row["topics"]) or []
        except (json.JSONDecodeError, TypeError):
            topics = []
        draft = None
        if row["pending_correction_draft"]:
            try:
                draft = json.loads(row["pending_correction_draft"])
            except (json.JSONDecodeError, TypeError):
                draft = None
        return {
            "id": row["id"],
            "title": row["title"],
            "type": "chat",
            "model_used": row["model_used"] or "owl",
            "topics": topics,
            "timestamp": format_timestamp(row["updated_at"]),
            "ts": row["updated_at"],
            "messages": [{"role": m["role"], "content": m["content"]} for m in msgs],
            "pending_correction_draft": draft,
        }


def rename_conversation(conv_id: str, username: str, title: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ? AND username = ? AND deleted_at IS NULL",
            (title, conv_id, username),
        )
        return cur.rowcount > 0


def delete_conversation(conv_id: str, username: str) -> bool:
    """Delete a conversation: soft-delete the row (its id is kept so correction
    provenance referencing it survives) but hard-delete the message bodies — the
    correction record snapshots the relevant text in the vault, so the chat
    transcript itself need not persist after the user removes it."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET deleted_at = ? WHERE id = ? AND username = ? AND deleted_at IS NULL",
            (_now_iso(), conv_id, username),
        )
        if cur.rowcount > 0:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        return cur.rowcount > 0
