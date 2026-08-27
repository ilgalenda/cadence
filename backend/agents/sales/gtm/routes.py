"""GTM's endpoint — propose target companies; the user selects."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agents.sales.gtm import agent
from auth import require_authed

router = APIRouter(prefix="/gtm", tags=["sales"])


class IdentifyRequest(BaseModel):
    vertical: Optional[str] = None
    seed_company: Optional[str] = None
    notes: Optional[str] = None
    config: dict = {}
    #: Fold the watchlist's recent findings into the notes. Default on; no effect
    #: when the watchlist is empty.
    use_signals: bool = True


@router.post("/identify")
def identify(req: IdentifyRequest, user: dict = Depends(require_authed)):
    """Propose accounts worth approaching. Nothing is started by asking."""
    analysis = {
        "vertical": req.vertical or "",
        "seed_company": req.seed_company or "",
        "notes": req.notes or "",
    }
    return agent.identify(user["username"], analysis, req.config, use_signals=req.use_signals)
