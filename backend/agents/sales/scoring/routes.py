"""Lead Scoring's endpoints — the behavioural read of one lead, and the site map
that read is graded against.

The page map lives here because `services/sitemap.py` exists only to feed
`services/lead_scoring.py`. It used to hang off the retired `lead` router, where
nothing ever called it; putting it beside its consumer is what makes it findable.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.sales.scoring import agent
from agents.services import lead_scoring, sitemap
from auth import require_admin, require_authed

router = APIRouter(prefix="/leads", tags=["sales"])


class AnalyseRequest(BaseModel):
    text: Optional[str] = None
    structured: Optional[dict] = None
    image_b64: Optional[str] = None
    image_media_type: Optional[str] = None


@router.post("/analyze")
def analyse(req: AnalyseRequest, user: dict = Depends(require_authed)):
    """Read a lead signal and attach its deterministic score."""
    if not (req.text or req.structured or req.image_b64):
        raise HTTPException(status_code=400, detail="Provide text, structured fields, or an image.")
    try:
        return agent.analyse(
            user["username"], text=req.text, structured=req.structured,
            image_b64=req.image_b64, image_media_type=req.image_media_type,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Signal analysis failed: {e}")


@router.get("/scale")
def get_scale(_user: dict = Depends(require_authed)):
    """What the scorer measures, out of what, and where each grade begins.

    Read by the scoring page so it can explain the model on an empty screen. The
    numbers live in one place; a surface that hard-coded them would drift the
    first time a ceiling moved.
    """
    return lead_scoring.scale()


@router.get("/page-map")
def get_page_map(_user: dict = Depends(require_authed)):
    """The site map scoring grades paths against; kicks off a lazy refresh if stale."""
    sitemap.maybe_refresh_page_map()
    payload = sitemap.load_page_map()
    if not payload:
        return {"generated_at": None, "count": 0, "map": {}, "unmapped": [], "status": "building"}
    return payload


@router.post("/page-map/refresh")
def refresh_page_map(_admin: dict = Depends(require_admin)):
    """Force a synchronous refresh from the live sitemap. Admin only — it hits the
    public site, and a stampede of refreshes is a self-inflicted load test."""
    try:
        payload = sitemap.refresh_page_map()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Page-map refresh failed: {e}")
    return {
        "generated_at": payload["generated_at"],
        "count": payload["count"],
        "unmapped": payload["unmapped"],
    }
