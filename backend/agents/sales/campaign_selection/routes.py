"""Campaign Selection's own surface — `/api/sales/campaign`.

One endpoint, no saving and no gate. Canon puts the human step at the *choosing*,
so there is nothing to file for approval; and the plan is a pure function of the
lead, so recomputing it is cheaper than storing it and safer than storing it
against a playbook that changes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agents.sales.campaign_selection import agent
from auth import require_authed

router = APIRouter(prefix="/campaign", tags=["sales-campaign-selection"])


class SelectRequest(BaseModel):
    #: Lead scoring's whole verdict, when the run has one. The plan is computed
    #: from it, which is what makes running this inside a path better than by hand.
    lead: Optional[dict] = None
    #: Overrides, for a caller who knows better than the verdict does.
    signal_type: str = ""
    signal_strength: str = ""
    has_named_contact: Optional[bool] = None


@router.post("/select")
def select(req: SelectRequest, _user: dict = Depends(require_authed)):
    """Compute the eligible campaign plan.

    Never 400s: with no lead and no overrides it still returns the ABM default,
    which is a real answer for "we are going after them and nothing has happened
    yet" — and it says so in `assumed`.
    """
    return agent.select(
        lead=req.lead,
        signal_type=req.signal_type,
        signal_strength=req.signal_strength,
        has_named_contact=req.has_named_contact,
    )
