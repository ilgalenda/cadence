"""Owl organisation — projects and the folders inside them.

A **project** is the top-level container. Beyond grouping conversations it
carries standing **instructions**, which ride into every conversation filed
under it (injected on the uncached tail, so the shared persona+vault prefix
stays byte-stable — the same discipline as per-user memory).

A **folder** nests inside exactly one project and may nest inside another
folder. Conversations live in a folder, at a project's root, or unfiled.

Containment is deliberately soft: a conversation references its project and
folder by id with no foreign key, so **deleting a container never destroys
conversations**. Deleting a folder lifts its conversations to the project root;
deleting a project unfiles them. Both are explicit state transitions, written
in one transaction — never a silent cascade.

Every read and write is scoped by ``username``: ownership is enforced at the
data layer, not by the caller remembering to check.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from agents.owl.db import connect

NAME_MAX = 120
INSTRUCTIONS_MAX = 8000


class OrganisationError(ValueError):
    """A request that cannot be satisfied — unknown id, or an illegal move."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise OrganisationError("name is required")
    return cleaned[:NAME_MAX]


# ── Projects ────────────────────────────────────────────────────────────────

def _project_row(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "instructions": row["instructions"],
        "position": row["position"],
        "archived": row["archived_at"] is not None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_project(username: str, name: str, instructions: str = "") -> dict:
    """Create a project, placed after the user's existing ones."""
    project_id = uuid.uuid4().hex
    now = _now_iso()
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM projects WHERE username = ?",
            (username,),
        ).fetchone()
        conn.execute(
            """INSERT INTO projects (id, username, name, instructions, position, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (project_id, username, _clean_name(name), (instructions or "")[:INSTRUCTIONS_MAX],
             row["next"], now, now),
        )
        created = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(created)


def list_projects(username: str, *, include_archived: bool = False) -> list[dict]:
    """The user's projects in their chosen order, each with its conversation count."""
    clause = "" if include_archived else "AND p.archived_at IS NULL"
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT p.*,
                       (SELECT COUNT(*) FROM conversations c
                         WHERE c.project_id = p.id AND c.deleted_at IS NULL
                           AND c.archived_at IS NULL) AS conversation_count
                  FROM projects p
                 WHERE p.username = ? {clause}
                 ORDER BY p.position, p.created_at""",
            (username,),
        ).fetchall()
    return [{**_project_row(r), "conversation_count": r["conversation_count"]} for r in rows]


def get_project(project_id: str, username: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND username = ?", (project_id, username),
        ).fetchone()
    return _project_row(row) if row else None


def update_project(
    project_id: str,
    username: str,
    *,
    name: Optional[str] = None,
    instructions: Optional[str] = None,
) -> dict:
    """Rename a project and/or replace its standing instructions."""
    if name is None and instructions is None:
        raise OrganisationError("nothing to update")
    sets, params = ["updated_at = ?"], [_now_iso()]
    if name is not None:
        sets.append("name = ?")
        params.append(_clean_name(name))
    if instructions is not None:
        sets.append("instructions = ?")
        params.append(instructions[:INSTRUCTIONS_MAX])
    params += [project_id, username]

    with connect() as conn:
        cur = conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE id = ? AND username = ?", params,
        )
        if cur.rowcount == 0:
            raise OrganisationError("project not found")
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(row)


def set_project_archived(project_id: str, username: str, archived: bool) -> dict:
    """Archive or restore a project. Its conversations are untouched either way."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE projects SET archived_at = ?, updated_at = ? WHERE id = ? AND username = ?",
            (_now_iso() if archived else None, _now_iso(), project_id, username),
        )
        if cur.rowcount == 0:
            raise OrganisationError("project not found")
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(row)


def delete_project(project_id: str, username: str) -> int:
    """Delete a project. Its folders go with it; its conversations are unfiled.

    Returns the number of conversations released. Conversations are never
    destroyed by deleting a container — the user asked to remove the grouping,
    not the work.
    """
    with connect() as conn:
        owned = conn.execute(
            "SELECT 1 FROM projects WHERE id = ? AND username = ?", (project_id, username),
        ).fetchone()
        if owned is None:
            raise OrganisationError("project not found")
        cur = conn.execute(
            """UPDATE conversations SET project_id = NULL, folder_id = NULL
                WHERE project_id = ? AND username = ?""",
            (project_id, username),
        )
        released = cur.rowcount
        # Folders cascade via their FK to projects.
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return released


def reorder_projects(username: str, ordered_ids: list[str]) -> None:
    """Apply an explicit order.

    Listed projects take positions 0..n-1 in the order given. Anything the caller
    did not list keeps its relative order and sits behind them, so a partial list
    (a drag within the visible set) never scrambles the rest.
    """
    if not ordered_ids:
        return
    with connect() as conn:
        owned = {
            r["id"] for r in conn.execute(
                "SELECT id FROM projects WHERE username = ?", (username,),
            )
        }
        unknown = [pid for pid in ordered_ids if pid not in owned]
        if unknown:
            raise OrganisationError(f"unknown project ids: {', '.join(unknown)}")

        remainder = conn.execute(
            f"""SELECT id FROM projects
                 WHERE username = ? AND id NOT IN ({','.join('?' * len(ordered_ids))})
                 ORDER BY position, created_at""",
            [username, *ordered_ids],
        ).fetchall()

        for position, project_id in enumerate([*ordered_ids, *(r["id"] for r in remainder)]):
            conn.execute(
                "UPDATE projects SET position = ? WHERE id = ? AND username = ?",
                (position, project_id, username),
            )


def project_instructions(project_id: Optional[str], username: str) -> str:
    """The standing instructions for a project, or '' when there are none."""
    if not project_id:
        return ""
    with connect() as conn:
        row = conn.execute(
            "SELECT instructions FROM projects WHERE id = ? AND username = ?",
            (project_id, username),
        ).fetchone()
    return (row["instructions"] or "").strip() if row else ""


# ── Folders ─────────────────────────────────────────────────────────────────

def _folder_row(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "parent_id": row["parent_id"],
        "position": row["position"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _assert_owns_project(conn, project_id: str, username: str) -> None:
    if conn.execute(
        "SELECT 1 FROM projects WHERE id = ? AND username = ?", (project_id, username),
    ).fetchone() is None:
        raise OrganisationError("project not found")


def create_folder(
    project_id: str,
    username: str,
    name: str,
    parent_id: Optional[str] = None,
) -> dict:
    """Create a folder at a project's root, or inside another folder of the same project."""
    folder_id = uuid.uuid4().hex
    now = _now_iso()
    with connect() as conn:
        _assert_owns_project(conn, project_id, username)
        if parent_id is not None:
            parent = conn.execute(
                "SELECT project_id FROM folders WHERE id = ? AND username = ?",
                (parent_id, username),
            ).fetchone()
            if parent is None:
                raise OrganisationError("parent folder not found")
            if parent["project_id"] != project_id:
                raise OrganisationError("parent folder belongs to a different project")
        row = conn.execute(
            """SELECT COALESCE(MAX(position), -1) + 1 AS next FROM folders
                WHERE project_id = ? AND parent_id IS ?""",
            (project_id, parent_id),
        ).fetchone()
        conn.execute(
            """INSERT INTO folders (id, project_id, username, name, parent_id, position, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (folder_id, project_id, username, _clean_name(name), parent_id, row["next"], now, now),
        )
        created = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
    return _folder_row(created)


def list_folders(project_id: str, username: str) -> list[dict]:
    """Every folder in a project, flat, each with its direct conversation count."""
    with connect() as conn:
        _assert_owns_project(conn, project_id, username)
        rows = conn.execute(
            """SELECT f.*,
                      (SELECT COUNT(*) FROM conversations c
                        WHERE c.folder_id = f.id AND c.deleted_at IS NULL
                          AND c.archived_at IS NULL) AS conversation_count
                 FROM folders f
                WHERE f.project_id = ? AND f.username = ?
                ORDER BY f.position, f.created_at""",
            (project_id, username),
        ).fetchall()
    return [{**_folder_row(r), "conversation_count": r["conversation_count"]} for r in rows]


def folder_tree(project_id: str, username: str) -> list[dict]:
    """The project's folders nested, roots first, each with a ``children`` list."""
    flat = list_folders(project_id, username)
    by_id = {f["id"]: {**f, "children": []} for f in flat}
    roots = []
    for folder in flat:
        node = by_id[folder["id"]]
        parent = by_id.get(folder["parent_id"]) if folder["parent_id"] else None
        (parent["children"] if parent else roots).append(node)
    return roots


def rename_folder(folder_id: str, username: str, name: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE folders SET name = ?, updated_at = ? WHERE id = ? AND username = ?",
            (_clean_name(name), _now_iso(), folder_id, username),
        )
        if cur.rowcount == 0:
            raise OrganisationError("folder not found")
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
    return _folder_row(row)


def _descendant_ids(conn, folder_id: str) -> set[str]:
    """Every folder beneath ``folder_id``, exclusive of itself."""
    found: set[str] = set()
    frontier = [folder_id]
    while frontier:
        rows = conn.execute(
            f"SELECT id FROM folders WHERE parent_id IN ({','.join('?' * len(frontier))})",
            frontier,
        ).fetchall()
        frontier = [r["id"] for r in rows if r["id"] not in found]
        found.update(frontier)
    return found


def move_folder(folder_id: str, username: str, parent_id: Optional[str]) -> dict:
    """Re-parent a folder within its project. Refuses to create a cycle."""
    with connect() as conn:
        folder = conn.execute(
            "SELECT * FROM folders WHERE id = ? AND username = ?", (folder_id, username),
        ).fetchone()
        if folder is None:
            raise OrganisationError("folder not found")

        if parent_id is not None:
            if parent_id == folder_id:
                raise OrganisationError("a folder cannot contain itself")
            parent = conn.execute(
                "SELECT project_id FROM folders WHERE id = ? AND username = ?",
                (parent_id, username),
            ).fetchone()
            if parent is None:
                raise OrganisationError("parent folder not found")
            if parent["project_id"] != folder["project_id"]:
                raise OrganisationError("cannot move a folder into a different project")
            if parent_id in _descendant_ids(conn, folder_id):
                raise OrganisationError("cannot move a folder into its own descendant")

        row = conn.execute(
            """SELECT COALESCE(MAX(position), -1) + 1 AS next FROM folders
                WHERE project_id = ? AND parent_id IS ?""",
            (folder["project_id"], parent_id),
        ).fetchone()
        conn.execute(
            "UPDATE folders SET parent_id = ?, position = ?, updated_at = ? WHERE id = ?",
            (parent_id, row["next"], _now_iso(), folder_id),
        )
        moved = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
    return _folder_row(moved)


def delete_folder(folder_id: str, username: str) -> int:
    """Delete a folder and its subfolders, lifting every affected conversation
    to the project root. Returns the number of conversations released."""
    with connect() as conn:
        folder = conn.execute(
            "SELECT 1 FROM folders WHERE id = ? AND username = ?", (folder_id, username),
        ).fetchone()
        if folder is None:
            raise OrganisationError("folder not found")
        doomed = [folder_id, *_descendant_ids(conn, folder_id)]
        placeholders = ",".join("?" * len(doomed))
        cur = conn.execute(
            f"""UPDATE conversations SET folder_id = NULL
                 WHERE folder_id IN ({placeholders}) AND username = ?""",
            [*doomed, username],
        )
        released = cur.rowcount
        # Subfolders cascade via their self-referential FK.
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
    return released


def assert_destination(
    username: str,
    project_id: Optional[str],
    folder_id: Optional[str],
) -> None:
    """Validate a (project, folder) destination before a conversation is moved there.

    A folder always implies its own project, so passing a folder that sits
    elsewhere is a contradiction rather than something to silently reconcile.
    """
    if folder_id is not None and project_id is None:
        raise OrganisationError("a folder destination requires its project")
    with connect() as conn:
        if project_id is not None:
            _assert_owns_project(conn, project_id, username)
        if folder_id is not None:
            row = conn.execute(
                "SELECT project_id FROM folders WHERE id = ? AND username = ?",
                (folder_id, username),
            ).fetchone()
            if row is None:
                raise OrganisationError("folder not found")
            if row["project_id"] != project_id:
                raise OrganisationError("folder does not belong to that project")
