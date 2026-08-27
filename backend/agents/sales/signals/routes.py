"""Signals' surface — `/api/sales/signals`.

The watchlist, and what has been found on it. Reading the watchlist is free; checking
it costs a web search per account, so the two are separate calls and only one of them
can spend anything.

`/detect` and `/signal-types` arrived here from X-ray (Sam, 2026-08-24). A sweep for
people showing a signal belongs where the signal is already the subject; X-ray now
answers only the grounded question — *given an account and why it matters, who are
the people*.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.sales.signals import agent
from agents.sales.store import signals as store
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/signals", tags=["sales-signals"])


class WatchRequest(BaseModel):
    company: str


class SweepRequest(BaseModel):
    #: Re-check accounts even if they were checked recently. Costs a search each.
    force: bool = False


class DetectRequest(BaseModel):
    signal_type: str
    icp_config: dict = {}


SIGNAL_TYPES = [
    "competitor_engagement",
    "influencer_engagement",
    "job_change",
    "funding",
    "top_icp",
    "company_engagement",
]


@router.get("/signal-types")
def signal_types(_user: dict = Depends(require_authed)):
    """The buying signals the people sweep understands."""
    return SIGNAL_TYPES


@router.post("/detect")
def detect(req: DetectRequest, user: dict = Depends(require_authed)):
    """People showing a buying signal, across companies.

    Unlike `/sweep`, which asks what happened at accounts already being watched,
    this asks who — anywhere — is showing a named signal. What it finds is a
    person and the account they point at, which is what makes it a way *onto* the
    watchlist rather than a report from it.
    """
    if req.signal_type not in SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown signal type {req.signal_type!r}.")
    return agent.detect(user["username"], req.signal_type, req.icp_config)


@router.get("/watchlist")
def watchlist(request: Request, user: dict = Depends(require_authed)):
    """The watched accounts and what has been found on each.

    **Kicks a background sweep if anything is due**, and says whether it did — this is
    what "scheduled" means in an app with no scheduler, and the page tells the person
    so rather than implying an overnight watch. Returns immediately either way; the
    findings from that sweep appear on the next load.
    """
    sandbox = is_sandbox(request)
    started = agent.maybe_sweep(user["username"], sandbox=sandbox)

    entries = store.watchlist(user["username"], sandbox)
    return {
        "sweeping": started,
        "watched": [
            {
                "id": entry.get("id"),
                "company": entry.get("company"),
                "added_at": entry.get("added_at"),
                "last_checked_at": entry.get("last_checked_at") or "",
                "due": store.stale(entry),
                "recent": entry.get("recent") or [],
            }
            for entry in entries
        ],
    }


@router.post("/watch", status_code=201)
def watch(req: WatchRequest, request: Request, user: dict = Depends(require_authed)):
    """Start watching an account. Watching one twice is not an error."""
    try:
        return store.watch(user["username"], req.company, sandbox=is_sandbox(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/watch/{entry_id}")
def unwatch(entry_id: str, request: Request, user: dict = Depends(require_authed)):
    if not store.unwatch(entry_id, user["username"], sandbox=is_sandbox(request)):
        raise HTTPException(status_code=404, detail="That account is not on your watchlist.")
    return {"ok": True}


@router.post("/sweep")
def sweep(req: SweepRequest, request: Request, user: dict = Depends(require_authed)):
    """Check the watchlist now, and wait for the result.

    Synchronous on purpose: this is the *Check now* button, and somebody is watching
    it. The background path is `/watchlist`, which returns straight away.
    """
    return agent.sweep(user["username"], force=req.force, sandbox=is_sandbox(request))
