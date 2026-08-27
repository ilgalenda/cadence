"""HTTP surface for Owl's organisation layer — projects, folders, placement, search.

Mounted onto the Owl router, which supplies the ``/api/owl`` prefix — this
router deliberately declares none of its own, or the two would compose into
``/api/owl/api/owl/…``. Kept separate from ``routes.py`` because chat and
organisation are different jobs: one streams generation, the other is CRUD over
the conversation tree.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.owl import projects, storage
from agents.owl.projects import OrganisationError
from auth import require_authed

router = APIRouter(tags=["owl"])


def _fail(error: OrganisationError) -> HTTPException:
    """Map a domain error to the right status: missing is 404, illegal is 400."""
    status = 404 if "not found" in str(error) else 400
    return HTTPException(status_code=status, detail=str(error))


# ── Request bodies ──────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    instructions: str = ""


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None


class ArchiveRequest(BaseModel):
    archived: bool


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None


class FolderPatch(BaseModel):
    name: Optional[str] = None
    # Present-but-null means "move to the project root", so the two operations
    # are distinguished by whether the caller sent the key at all.
    parent_id: Optional[str] = None
    move: bool = False


class PlacementRequest(BaseModel):
    project_id: Optional[str] = None
    folder_id: Optional[str] = None


class PinRequest(BaseModel):
    pinned: bool


# ── Projects ────────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(include_archived: bool = False, user: dict = Depends(require_authed)):
    return projects.list_projects(user["username"], include_archived=include_archived)


@router.post("/projects", status_code=201)
def create_project(req: ProjectCreate, user: dict = Depends(require_authed)):
    try:
        return projects.create_project(user["username"], req.name, req.instructions)
    except OrganisationError as e:
        raise _fail(e)


@router.post("/projects/reorder")
def reorder_projects(req: ReorderRequest, user: dict = Depends(require_authed)):
    try:
        projects.reorder_projects(user["username"], req.ordered_ids)
    except OrganisationError as e:
        raise _fail(e)
    return {"ok": True}


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: dict = Depends(require_authed)):
    project = projects.get_project(project_id, user["username"])
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.patch("/projects/{project_id}")
def update_project(project_id: str, req: ProjectPatch, user: dict = Depends(require_authed)):
    try:
        return projects.update_project(
            project_id, user["username"], name=req.name, instructions=req.instructions,
        )
    except OrganisationError as e:
        raise _fail(e)


@router.post("/projects/{project_id}/archive")
def archive_project(project_id: str, req: ArchiveRequest, user: dict = Depends(require_authed)):
    try:
        return projects.set_project_archived(project_id, user["username"], req.archived)
    except OrganisationError as e:
        raise _fail(e)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: dict = Depends(require_authed)):
    """Delete a project. Its folders go too; its conversations are unfiled, not destroyed."""
    try:
        released = projects.delete_project(project_id, user["username"])
    except OrganisationError as e:
        raise _fail(e)
    return {"ok": True, "conversations_unfiled": released}


# ── Folders ─────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/folders")
def list_folders(project_id: str, user: dict = Depends(require_authed)):
    """The project's folders, nested."""
    try:
        return projects.folder_tree(project_id, user["username"])
    except OrganisationError as e:
        raise _fail(e)


@router.post("/projects/{project_id}/folders", status_code=201)
def create_folder(project_id: str, req: FolderCreate, user: dict = Depends(require_authed)):
    try:
        return projects.create_folder(project_id, user["username"], req.name, req.parent_id)
    except OrganisationError as e:
        raise _fail(e)


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: str, req: FolderPatch, user: dict = Depends(require_authed)):
    """Rename a folder, re-parent it, or both. Set ``move`` to apply ``parent_id``."""
    if req.name is None and not req.move:
        raise HTTPException(status_code=400, detail="nothing to update")
    try:
        result = None
        if req.name is not None:
            result = projects.rename_folder(folder_id, user["username"], req.name)
        if req.move:
            result = projects.move_folder(folder_id, user["username"], req.parent_id)
        return result
    except OrganisationError as e:
        raise _fail(e)


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, user: dict = Depends(require_authed)):
    """Delete a folder and its subfolders, lifting their conversations to the project root."""
    try:
        released = projects.delete_folder(folder_id, user["username"])
    except OrganisationError as e:
        raise _fail(e)
    return {"ok": True, "conversations_released": released}


# ── Conversation placement ──────────────────────────────────────────────────

@router.patch("/sessions/{session_id}/placement")
def move_conversation(session_id: str, req: PlacementRequest, user: dict = Depends(require_authed)):
    """File a conversation under a project/folder, or unfile it by sending both null."""
    try:
        projects.assert_destination(user["username"], req.project_id, req.folder_id)
    except OrganisationError as e:
        raise _fail(e)
    if not storage.move_conversation(session_id, user["username"], req.project_id, req.folder_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True, "project_id": req.project_id, "folder_id": req.folder_id}


@router.post("/sessions/{session_id}/pin")
def pin_conversation(session_id: str, req: PinRequest, user: dict = Depends(require_authed)):
    if not storage.set_pinned(session_id, user["username"], req.pinned):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True, "pinned": req.pinned}


@router.post("/sessions/{session_id}/archive")
def archive_conversation(session_id: str, req: ArchiveRequest, user: dict = Depends(require_authed)):
    """Archive a conversation out of the default lists. Unlike deletion, reversible."""
    if not storage.set_archived(session_id, user["username"], req.archived):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True, "archived": req.archived}


# ── Search ──────────────────────────────────────────────────────────────────

@router.get("/search")
def search(
    q: str,
    project_id: Optional[str] = None,
    limit: int = 40,
    user: dict = Depends(require_authed),
):
    """Search message bodies across conversations, optionally within one project.

    Returns one result per matching message, with a snippet — so a hit points at
    where it actually is, not merely at the conversation that contained it.
    """
    scope = storage.UNFILTERED if project_id is None else project_id
    return storage.search_messages(user["username"], q, project_id=scope, limit=limit)
