from __future__ import annotations
"""Forecasting / pipeline / revenue agent.

Syncs deals from a CRM connector (stubbed MockHubSpotConnector by default) into
per-user storage, then serves deterministic analytics: pipeline by vertical and
stage, a probability-weighted forecast, and pipeline-hygiene flags.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from agents.forecast import analytics, pipeline_manager, storage
from agents.forecast.crm import get_connector
from agents.shared.notifications import send_admin_email
from auth import is_sandbox, require_agent_access

_user = require_agent_access("forecast")
router = APIRouter(prefix="/api/forecast", tags=["forecast"], dependencies=[Depends(_user)])


def _deals(user: dict, request: Request) -> list[dict]:
    return storage.deals.load_user(user["username"], sandbox=is_sandbox(request))


class SyncResponse(BaseModel):
    synced: int


@router.get("/connector")
def connector_status(user: dict = Depends(_user)):
    return {"connected": get_connector().is_connected()}


@router.post("/sync")
def sync(request: Request, user: dict = Depends(_user)) -> SyncResponse:
    """Pull deals from the CRM connector into this user's pipeline store."""
    sandbox = is_sandbox(request)
    deals = get_connector().fetch_deals()
    for d in deals:
        storage.deals.upsert(dict(d), username=user["username"], sandbox=sandbox)
    return SyncResponse(synced=len(deals))


@router.get("/deals")
def list_deals(request: Request, user: dict = Depends(_user)):
    return _deals(user, request)


@router.get("/pipeline")
def pipeline(request: Request, user: dict = Depends(_user)):
    deals = _deals(user, request)
    return {
        "by_vertical": analytics.group_by(deals, "vertical"),
        "by_stage": analytics.group_by(deals, "stage"),
    }


@router.get("/forecast")
def forecast(request: Request, user: dict = Depends(_user)):
    return analytics.weighted_forecast(_deals(user, request))


@router.get("/hygiene")
def hygiene(request: Request, user: dict = Depends(_user)):
    today = datetime.now(timezone.utc).date()
    issues = analytics.hygiene(_deals(user, request), today)
    return {"issues": issues, "count": len(issues)}


@router.get("/stats")
def stats(request: Request, user: dict = Depends(_user)):
    deals = _deals(user, request)
    fc = analytics.weighted_forecast(deals)
    return {
        "deals_total": len(deals),
        "open_value": fc["open_value"],
        "weighted_forecast": fc["weighted_forecast"],
    }


# ---------------------------------------------------------------------------
# Pipeline Manager — the daily morning briefing (deterministic)
# ---------------------------------------------------------------------------

@router.get("/briefing")
def briefing(request: Request, user: dict = Depends(_user)):
    """Today's deterministic pipeline briefing: summary + quiet + aging + overdue."""
    today = datetime.now(timezone.utc).date()
    return pipeline_manager.build_briefing(_deals(user, request), today)


@router.post("/briefing/send")
def send_briefing(request: Request, user: dict = Depends(_user)):
    """Email today's briefing via the configured admin SMTP. {sent:false} if SMTP is unset."""
    today = datetime.now(timezone.utc).date()
    brief = pipeline_manager.build_briefing(_deals(user, request), today)
    body = pipeline_manager.render_briefing_text(brief)
    sent = send_admin_email(f"[Cadence] Pipeline morning briefing — {brief['date']}", body)
    return {"sent": sent}
