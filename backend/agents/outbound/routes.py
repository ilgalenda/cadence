"""Outbound's surface — `/api/outbound`.

The ABM tracker: which accounts are being worked, how far each sequence has got,
and what each one is worth.

**Not a sales agent, deliberately.** There is no LLM call anywhere in this package
and it is not registered in `agents/sales/registry.py`, so Owl cannot invoke it —
the same reasoning `agents/events` records. GTM *fills* a tracker; the tracker
itself is a record and a set of counters. Mounting it top-level, beside `events`,
keeps that visible in the route table rather than resting on somebody remembering
it.

**Owner-scoped, and an unreachable tracker says "No such tracker".** A tracker is
one person's working list, so the scope is a predicate on the reads *and* the
writes; an admin sees every tracker. Answering with a 404-shaped message rather than
a refusal is the rule `agents/events` set, because "you may not" leaks that it
exists.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agents.outbound import export, store
from agents.sales.store import signals as signals_store
from auth import is_admin, require_authed

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


class TrackerRequest(BaseModel):
    """A new tracker and the goals its counters are read against."""

    name: str
    goal_gbp: int = 0
    target_touches: int = 0
    target_replies: int = 0
    target_calls: int = 0
    target_qualified: int = 0


class RowsRequest(BaseModel):
    """Accounts to put on a tracker, in the shape GTM proposes them."""

    rows: list[dict] = Field(default_factory=list)


class TouchRequest(BaseModel):
    index: int
    fired: bool = True
    source: str = ""


class StatusRequest(BaseModel):
    status: str
    source: str = ""


class RowEditRequest(BaseModel):
    """Only the fields a person owns. Unknown keys are refused by the store."""

    changes: dict = Field(default_factory=dict)


class ArtifactRequest(BaseModel):
    url: str


def _ok(fn, *args, **kwargs):
    """Run a store call, turning its business rules into a 400.

    The store raises `ValueError` with a message written for the person who typed
    the thing; the page renders `detail` verbatim.
    """
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _reachable_tracker(tracker_id: str, user: dict) -> dict:
    """The tracker, or a 404 — including when it belongs to somebody else."""
    tracker = store.get_tracker(tracker_id)
    if not tracker or (tracker["username"] != user["username"] and not is_admin(user)):
        raise HTTPException(status_code=404, detail="No such tracker")
    return tracker


def _reachable_row(row_id: str, user: dict) -> dict:
    """The row, or a 404 — enforced through the tracker that owns it."""
    row = store.get_row(row_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such account on any tracker")
    _reachable_tracker(row["tracker_id"], user)
    return row


# ---------------------------------------------------------------------------
# Trackers
# ---------------------------------------------------------------------------

@router.get("/trackers")
def list_trackers(user: dict = Depends(require_authed)) -> dict:
    """Every tracker this person may see, newest first."""
    username = None if is_admin(user) else user["username"]
    trackers = store.list_trackers(username)
    return {"trackers": [{**t, "counters": store.counters(t["id"])} for t in trackers]}


@router.post("/trackers")
def create_tracker(req: TrackerRequest, user: dict = Depends(require_authed)) -> dict:
    return _ok(
        store.create_tracker,
        req.name,
        user["username"],
        goal_gbp=req.goal_gbp,
        target_touches=req.target_touches,
        target_replies=req.target_replies,
        target_calls=req.target_calls,
        target_qualified=req.target_qualified,
    )


@router.get("/trackers/{tracker_id}")
def read_tracker(tracker_id: str, user: dict = Depends(require_authed)) -> dict:
    """One tracker: its accounts, each account's touch trail, and the counters."""
    tracker = _reachable_tracker(tracker_id, user)
    return {
        "tracker": tracker,
        "rows": store.get_rows(tracker_id),
        "counters": store.counters(tracker_id),
    }


@router.post("/trackers/{tracker_id}/rows")
def add_rows(tracker_id: str, req: RowsRequest, user: dict = Depends(require_authed)) -> dict:
    _reachable_tracker(tracker_id, user)
    return _ok(store.add_rows, tracker_id, req.rows, user["username"])


@router.get("/trackers/{tracker_id}/export", response_class=HTMLResponse)
def export_tracker(tracker_id: str, user: dict = Depends(require_authed)) -> HTMLResponse:
    """This tracker as a standalone, read-only page.

    Returned as HTML rather than as a download because the caller is usually
    publishing it, not filing it. It carries no Save button and no `window.claude`
    call: Cadence owns the record, and a snapshot that could be ticked would only
    disagree with it — which is the failure the whole surface exists to end.
    """
    _reachable_tracker(tracker_id, user)
    return HTMLResponse(_ok(export.render, tracker_id))


@router.delete("/trackers/{tracker_id}")
def delete_tracker(tracker_id: str, user: dict = Depends(require_authed)) -> dict:
    """Delete a campaign and everything recorded against it.

    Owner-scoped like every other write here, and the only destructive route in
    the package. The page must confirm first and say what goes — this endpoint
    reports what it removed, but by then it is gone.
    """
    _reachable_tracker(tracker_id, user)
    return _ok(store.delete_tracker, tracker_id)


@router.post("/trackers/{tracker_id}/reprice")
def reprice(tracker_id: str, user: dict = Depends(require_authed)) -> dict:
    """Re-run the valuation, e.g. after the price catalogue changed."""
    _reachable_tracker(tracker_id, user)
    return _ok(store.reprice, tracker_id)


@router.put("/trackers/{tracker_id}/artifact")
def set_artifact(tracker_id: str, req: ArtifactRequest, user: dict = Depends(require_authed)) -> dict:
    """Record where this tracker's published share view lives."""
    _reachable_tracker(tracker_id, user)
    return _ok(store.set_artifact_url, tracker_id, req.url)


@router.post("/trackers/{tracker_id}/watch")
def watch_accounts(tracker_id: str, user: dict = Depends(require_authed)) -> dict:
    """Put every account on this tracker onto the Signals watchlist.

    This is what closes the trigger loop. `signals.digest` only reports on accounts
    somebody is already watching, so a freshly proposed list has no triggers by
    construction — GTM proposes, the tracker watches, Signals finds, and the
    trigger fills in on the next read. Without this step the trigger column would
    stay empty for ever, or be filled in by invention.

    **The watchlist is capped at fifty accounts**, because every watched account
    costs a web search per sweep. A tracker larger than the remaining headroom is
    therefore watched as far as it goes and the rest are **reported, not silently
    dropped** — and this never raises after watching some, because a half-applied
    call that reports failure is the worst of both. Which accounts to watch out of a
    longer list is a decision for the person, not for this endpoint.
    """
    _reachable_tracker(tracker_id, user)
    watched: list[str] = []
    refused: list[dict] = []
    for row in store.get_rows(tracker_id):
        try:
            signals_store.watch(user["username"], row["account"])
        except ValueError as e:
            refused.append({"account": row["account"], "why": str(e)})
            continue
        watched.append(row["account"])
    return {"watching": watched, "count": len(watched), "refused": refused}


# ---------------------------------------------------------------------------
# Rows — what has happened
# ---------------------------------------------------------------------------

@router.post("/rows/{row_id}/touch")
def fire_touch(row_id: str, req: TouchRequest, user: dict = Depends(require_authed)) -> dict:
    _reachable_row(row_id, user)
    return _ok(
        store.fire_touch, row_id, req.index, user["username"],
        fired=req.fired, source=req.source,
    )


@router.post("/rows/{row_id}/status")
def set_status(row_id: str, req: StatusRequest, user: dict = Depends(require_authed)) -> dict:
    _reachable_row(row_id, user)
    return _ok(store.set_status, row_id, req.status, user["username"], source=req.source)


@router.patch("/rows/{row_id}")
def update_row(row_id: str, req: RowEditRequest, user: dict = Depends(require_authed)) -> dict:
    _reachable_row(row_id, user)
    return _ok(store.update_row, row_id, req.changes, user["username"])


@router.get("/rows/{row_id}")
def read_row(row_id: str, user: dict = Depends(require_authed)) -> dict:
    """One account and its full trail — what was sent, when, and by whom."""
    return _reachable_row(row_id, user)
