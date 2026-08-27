"""Campaign Intelligence's own surface — `/api/sales/intel`.

One endpoint, and no saving. A research brief is filed because it costs a
web-search turn and sometimes Lusha credit; an outline costs two model calls
against local files, so it is cheaper to run again than to keep — and an outline
kept for a week is worse than useless once another call in that market lands.

Nothing here is gated: canon gives this agent no review gate, because it produces
preparation rather than anything a customer sees.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agents.sales.campaign_intelligence import agent
from auth import require_authed

router = APIRouter(prefix="/intel", tags=["sales-campaign-intelligence"])


class OutlineRequest(BaseModel):
    #: Optional: with a brief in hand the market is inferred from it, which is what
    #: happens when this runs as a path step after Research.
    vertical: str = ""
    company: str = ""
    brief: Optional[dict] = None
    notes: str = ""


@router.post("/outline")
def run_outline(req: OutlineRequest, user: dict = Depends(require_authed)):
    """Recall the market and outline how to approach it.

    Never 400s on a missing market: `other` is a real market in Memory's taxonomy
    and an outline over it is a legitimate answer, so there is nothing to refuse.
    """
    return agent.outline(
        user["username"],
        vertical=req.vertical,
        company=req.company,
        brief=req.brief,
        notes=req.notes,
    )
