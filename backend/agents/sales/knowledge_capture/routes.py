"""Knowledge Capture's surface — `/api/sales/capture`.

Two endpoints, and neither is the main path: capture normally happens as part of an
analysis. These exist for reading back what a call staged, and for re-running the
staging after a failure without paying for the reading again.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from agents.sales.knowledge_capture import agent
from agents.sales.store import calls as store
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/capture", tags=["sales-knowledge-capture"])


class CaptureRequest(BaseModel):
    call_id: str


@router.get("/learnings")
def learnings(request: Request, user: dict = Depends(require_authed)):
    """What this user's calls have taught us, newest first."""
    return store.load_learnings(user["username"], sandbox=is_sandbox(request))


@router.post("/recapture")
def recapture(req: CaptureRequest, request: Request, user: dict = Depends(require_authed)):
    """Stage again from an already-analysed call.

    Never 4xx on a repeat: `write_glossary_term` skips terms that already exist and
    the response says what was actually new, so running this twice is safe and
    honest rather than an error.
    """
    return agent.capture_from_call(
        user["username"], req.call_id, sandbox=is_sandbox(request),
    )
