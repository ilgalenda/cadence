"""Composer's surface — `/api/sales/composer`.

Composing and deciding are separate calls because the gate is the point: every
composition is filed pending, and approving it is a recorded human act. Nothing
here sends anything — Gmail drafting is Phase 4.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.sales.composer import agent
from auth import require_authed

router = APIRouter(prefix="/composer", tags=["sales-composer"])


class ComposeRequest(BaseModel):
    #: A Research brief. Its `subject.company` is what makes it usable.
    brief: dict
    channels: Optional[list[str]] = None
    notes: str = ""
    #: A Campaign Intelligence outline, when the path ran one. Optional — the
    #: touches are better with it, not impossible without it.
    intel: Optional[dict] = None
    #: The email address the email touch will be addressed to on approval. Optional:
    #: without it the touches are still written and filed, just not draftable.
    recipient: str = ""


class DecideRequest(BaseModel):
    review_id: str
    approve: bool
    notes: str = ""


class DraftAgainRequest(BaseModel):
    review_id: str


@router.post("/compose")
def compose(req: ComposeRequest, user: dict = Depends(require_authed)):
    """Write the touches for a brief and file them for review."""
    result = agent.compose(
        user["username"],
        brief=req.brief,
        channels=req.channels,
        notes=req.notes,
        intel=req.intel,
        recipient=req.recipient,
    )
    if result["error"] == "no_brief":
        raise HTTPException(
            status_code=400,
            detail="Research the account first — there is no brief to write from.",
        )
    return result


@router.get("/pending")
def pending(user: dict = Depends(require_authed)):
    """Touches awaiting this user's decision."""
    return agent.pending(user["username"])


@router.post("/decide")
def decide(req: DecideRequest, user: dict = Depends(require_authed)):
    """Record the decision. Approving means the person will send it, not that it went."""
    try:
        return agent.decide(
            user["username"], req.review_id, approve=req.approve, notes=req.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Those touches are no longer in the queue.")
    except ValueError as e:
        # The queue refuses to re-decide something already decided.
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/draft-again")
def draft_again(req: DraftAgainRequest, user: dict = Depends(require_authed)):
    """Retry the Gmail draft for touches already approved.

    Separate from `/decide` because the decision is not in question — only the
    delivery failed, and the queue rightly refuses to re-decide a terminal item.
    """
    try:
        return agent.draft_again(user["username"], req.review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Those touches are no longer in the queue.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
