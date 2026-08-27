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
    project_id: Optional[str] = None,
) -> None:
    """Persist the conversation row (creating it on the first turn) and append
    the user message.

    Called at stream *start* so the conversation id the client receives is
    always backed by a real row, and the user's message is never lost even if
    generation errors or returns empty. The title, model and project are locked
    on the first turn.
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
                   (id, username, title, model_used, topics, project_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv_id, username, title or "Chat", model_used,
                 json.dumps(topics[:3]), project_id, now, now),
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
        "project_id": row["project_id"],
        "folder_id": row["folder_id"],
        "pinned": row["pinned_at"] is not None,
        "archived": row["archived_at"] is not None,
    }


# Distinguishes "caller did not filter on this" from "caller asked for NULL",
# which is a real query: unfiled conversations, or a project's root.
UNFILTERED = object()


def _placement_clause(project_id, folder_id) -> tuple[str, list]:
    """SQL fragment + params for the project/folder filter."""
    clause, params = "", []
    if project_id is not UNFILTERED:
        clause += " AND project_id IS ?" if project_id is None else " AND project_id = ?"
        params.append(project_id)
    if folder_id is not UNFILTERED:
        clause += " AND folder_id IS ?" if folder_id is None else " AND folder_id = ?"
        params.append(folder_id)
    return clause, params


def list_conversations(
    username: str,
    query: Optional[str] = None,
    limit: int = SESSION_CAP,
    *,
    project_id=UNFILTERED,
    folder_id=UNFILTERED,
    include_archived: bool = False,
) -> list[dict]:
    """Summaries (no message bodies) for a user, pinned first then newest.

    ``project_id``/``folder_id`` default to unfiltered. Passing ``None`` is a
    real filter meaning "not filed" — an unfiled conversation, or one at a
    project's root — which is how the workspace asks for each part of the tree.
    """
    where = "username = ? AND deleted_at IS NULL"
    params: list = [username]

    if not include_archived:
        where += " AND archived_at IS NULL"

    placement, placement_params = _placement_clause(project_id, folder_id)
    where += placement
    params += placement_params

    if query:
        like = f"%{query}%"
        where += """ AND (title LIKE ? OR id IN (
                       SELECT conversation_id FROM messages WHERE content LIKE ?))"""
        params += [like, like]

    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM conversations WHERE {where}
                 ORDER BY pinned_at IS NULL, pinned_at DESC, updated_at DESC
                 LIMIT ?""",
            params,
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
            "project_id": row["project_id"],
            "folder_id": row["folder_id"],
            "pinned": row["pinned_at"] is not None,
            "archived": row["archived_at"] is not None,
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


def project_of(conv_id: str, username: str) -> Optional[str]:
    """The project a conversation is filed under, or None when unfiled."""
    with connect() as conn:
        row = conn.execute(
            "SELECT project_id FROM conversations WHERE id = ? AND username = ? AND deleted_at IS NULL",
            (conv_id, username),
        ).fetchone()
    return row["project_id"] if row else None


def move_conversation(
    conv_id: str,
    username: str,
    project_id: Optional[str],
    folder_id: Optional[str],
) -> bool:
    """File a conversation under a project/folder, or unfile it with both None.

    The destination is validated by the caller (``projects.assert_destination``)
    so an invalid move is rejected before anything is written.
    """
    with connect() as conn:
        cur = conn.execute(
            """UPDATE conversations SET project_id = ?, folder_id = ?
                WHERE id = ? AND username = ? AND deleted_at IS NULL""",
            (project_id, folder_id, conv_id, username),
        )
        return cur.rowcount > 0


def set_pinned(conv_id: str, username: str, pinned: bool) -> bool:
    """Pin a conversation to the top of its list, or unpin it."""
    with connect() as conn:
        cur = conn.execute(
            """UPDATE conversations SET pinned_at = ?
                WHERE id = ? AND username = ? AND deleted_at IS NULL""",
            (_now_iso() if pinned else None, conv_id, username),
        )
        return cur.rowcount > 0


def set_archived(conv_id: str, username: str, archived: bool) -> bool:
    """Archive a conversation out of the default lists, or restore it.

    Distinct from deletion: an archived conversation keeps its messages and can
    be brought back. Deletion destroys the transcript.
    """
    with connect() as conn:
        cur = conn.execute(
            """UPDATE conversations SET archived_at = ?
                WHERE id = ? AND username = ? AND deleted_at IS NULL""",
            (_now_iso() if archived else None, conv_id, username),
        )
        return cur.rowcount > 0


_SNIPPET_RADIUS = 90


def _snippet(content: str, query: str) -> str:
    """The matching phrase with a little context either side, for the results list."""
    at = content.lower().find(query.lower())
    if at == -1:
        return content[:_SNIPPET_RADIUS * 2].strip()
    start = max(0, at - _SNIPPET_RADIUS)
    end = min(len(content), at + len(query) + _SNIPPET_RADIUS)
    return ("…" if start else "") + content[start:end].strip() + ("…" if end < len(content) else "")


def search_messages(
    username: str,
    query: str,
    *,
    project_id=UNFILTERED,
    limit: int = 40,
) -> list[dict]:
    """Search message bodies across conversations, newest match first.

    Returns one row per matching *message* — the conversation it belongs to plus
    a snippet — so the workspace can show where the hit actually is rather than
    only which conversation contained it.

    LIKE rather than FTS5: a user holds at most ``SESSION_CAP`` conversations, so
    the scan is cheap and the store needs no shadow index to keep in step. If the
    cap ever rises materially, this is the place to introduce FTS.
    """
    term = (query or "").strip()
    if not term:
        return []

    where = "c.username = ? AND c.deleted_at IS NULL AND m.content LIKE ?"
    params: list = [username, f"%{term}%"]
    if project_id is not UNFILTERED:
        where += " AND c.project_id IS ?" if project_id is None else " AND c.project_id = ?"
        params.append(project_id)
    params.append(limit)

    with connect() as conn:
        rows = conn.execute(
            f"""SELECT m.content, m.role, m.created_at,
                       c.id AS conversation_id, c.title, c.project_id, c.folder_id
                  FROM messages m JOIN conversations c ON c.id = m.conversation_id
                 WHERE {where}
                 ORDER BY m.created_at DESC
                 LIMIT ?""",
            params,
        ).fetchall()

    return [{
        "conversation_id": r["conversation_id"],
        "title": r["title"],
        "project_id": r["project_id"],
        "folder_id": r["folder_id"],
        "role": r["role"],
        "snippet": _snippet(r["content"], term),
        "ts": r["created_at"],
    } for r in rows]


def delete_all_conversations(username: str) -> int:
    """Delete every one of this user's conversations. Returns how many went.

    Same contract as :func:`delete_conversation`, applied in bulk and in one
    transaction: the rows are soft-deleted so any correction provenance pointing
    at them survives, and the message bodies are hard-deleted because the vault
    already snapshots whatever text a correction relies on.

    Archived conversations are included — they are conversations, and this is
    the control that says "all". Already-deleted rows are skipped, so calling it
    twice is harmless and the second call reports zero.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM conversations WHERE username = ? AND deleted_at IS NULL",
            (username,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            return 0

        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE conversations SET deleted_at = ? WHERE id IN ({placeholders})",
            [_now_iso(), *ids],
        )
        conn.execute(
            f"DELETE FROM messages WHERE conversation_id IN ({placeholders})",
            ids,
        )
        return len(ids)


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
