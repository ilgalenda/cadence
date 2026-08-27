"""Recap's surface — `/api/sales/recap`.

Drafting and deciding are separate calls because the gate is the point: every recap
is filed pending, and approving it is a recorded human act. Nothing here sends
anything — Gmail drafting is Phase 4.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.sales.recap import agent
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/recap", tags=["sales-recap"])

#: Errors that mean "you asked about the wrong thing" rather than "it went wrong".
_NOT_FOUND = {"no_such_call": "That call is no longer here."}
_UNPROCESSABLE = {
    "no_usable_analysis": "That call has no reading to build a follow-up from — analyse it first.",
}


class DraftRequest(BaseModel):
    call_id: str
    #: The client's email address. A call analysis never supplies one, so this is
    #: whatever the person gives us — and without it the recap is still written and
    #: filed, just not draftable.
    recipient: str = ""
    notes: str = ""


class DecideRequest(BaseModel):
    review_id: str
    approve: bool
    notes: str = ""


class DraftAgainRequest(BaseModel):
    review_id: str


@router.post("/draft")
def draft(req: DraftRequest, request: Request, user: dict = Depends(require_authed)):
    """Write the follow-up for a call and file it for review."""
    out = agent.draft(
        user["username"],
        call_id=req.call_id,
        recipient=req.recipient,
        notes=req.notes,
        sandbox=is_sandbox(request),
    )

    if out["error"] in _NOT_FOUND:
        raise HTTPException(status_code=404, detail=_NOT_FOUND[out["error"]])
    if out["error"] in _UNPROCESSABLE:
        raise HTTPException(status_code=422, detail=_UNPROCESSABLE[out["error"]])
    if out["error"]:
        raise HTTPException(status_code=502, detail=f"Could not write the follow-up: {out['error']}")
    return out


@router.get("/pending")
def pending(user: dict = Depends(require_authed)):
    """Recaps awaiting this user's decision."""
    return agent.pending(user["username"])


@router.post("/decide")
def decide(req: DecideRequest, user: dict = Depends(require_authed)):
    """Record the decision. Approving means the person will send it, not that it went."""
    try:
        return agent.decide(
            user["username"], req.review_id, approve=req.approve, notes=req.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="That recap is no longer in the queue.")
    except ValueError as e:
        # The queue refuses to re-decide something already decided.
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/draft-again")
def draft_again(req: DraftAgainRequest, user: dict = Depends(require_authed)):
    """Retry the Gmail draft for a recap already approved."""
    try:
        return agent.draft_again(user["username"], req.review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="That recap is no longer in the queue.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
