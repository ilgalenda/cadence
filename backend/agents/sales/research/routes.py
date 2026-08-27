"""Research's own surface — `/api/sales/research`.

Running the research and keeping it are separate calls on purpose. A brief costs a
web-search turn, so the page runs one and shows it; saving is a second, deliberate
act. That way an exploratory look does not fill the list, and a brief worth keeping
survives a reload — the same reasoning behind X-ray's shortlists.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.sales.research import agent
from agents.sales.store import research as store
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/research", tags=["sales-research"])


class BriefRequest(BaseModel):
    company: str
    #: A picked X-ray row, or just a name. The agent accepts either.
    person: Optional[dict] = None
    #: Lead scoring's whole verdict, when the run has one — this is what makes the
    #: brief better than a by-hand search.
    lead: Optional[dict] = None
    notes: str = ""


class BriefSave(BaseModel):
    brief: dict
    id: Optional[str] = None


@router.post("/brief")
def run_brief(req: BriefRequest, user: dict = Depends(require_authed)):
    """Research a company, and a decision-maker when one is named."""
    if not req.company.strip():
        raise HTTPException(status_code=400, detail="Name a company to research.")

    return agent.brief(
        user["username"],
        company=req.company,
        person=req.person,
        lead=req.lead,
        notes=req.notes,
    )


@router.get("/briefs")
def list_briefs(request: Request, user: dict = Depends(require_authed)):
    """Saved briefs, newest first, as a browsable index without their bodies."""
    saved = store.load_user_briefs(user["username"], sandbox=is_sandbox(request))
    return [
        {
            "id": record.get("id"),
            "company": (record.get("subject") or {}).get("company") or "",
            "person": (record.get("subject") or {}).get("person") or "",
            "updated_at": record.get("updated_at") or record.get("created_at") or "",
        }
        for record in saved
    ]


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: str, request: Request, user: dict = Depends(require_authed)):
    record = store.get_brief(brief_id, user["username"], sandbox=is_sandbox(request))
    if record is None:
        raise HTTPException(status_code=404, detail="That brief no longer exists.")
    return record


@router.post("/briefs", status_code=201)
def save_brief(req: BriefSave, request: Request, user: dict = Depends(require_authed)):
    """Keep a brief. Re-saving with an id updates in place rather than duplicating."""
    subject = (req.brief or {}).get("subject") or {}
    if not (subject.get("company") or "").strip():
        raise HTTPException(status_code=400, detail="There is no brief to save.")

    record = store.save_brief(
        {**req.brief, "id": req.id},
        username=user["username"],
        sandbox=is_sandbox(request),
    )
    return {"id": record["id"], "company": subject.get("company")}


@router.delete("/briefs/{brief_id}")
def delete_brief(brief_id: str, request: Request, user: dict = Depends(require_authed)):
    if not store.delete_brief(brief_id, user["username"], sandbox=is_sandbox(request)):
        raise HTTPException(status_code=404, detail="That brief no longer exists.")
    return {"ok": True}
