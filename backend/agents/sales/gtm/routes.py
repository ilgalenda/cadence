"""GTM's endpoints — propose target companies, or a target list; the user selects.

Two modes, deliberately separate. `/identify` is the forty-second shortlist of
names. `/targets` is the classified list a tracker is built from, and it writes
nothing: it submits to the review queue, and approving is what creates the tracker.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.sales.gtm import agent, review
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


class TargetsRequest(BaseModel):
    """The same scope as `/identify`, for the richer mode."""

    vertical: Optional[str] = None
    seed_company: Optional[str] = None
    notes: Optional[str] = None
    config: dict = {}
    use_signals: bool = True
    #: Queue the result for review. On by default: a list that lands straight on a
    #: tracker skips the only exclusion check that exists.
    submit_for_review: bool = True


class ApproveRequest(BaseModel):
    """Approve a queued list, optionally onto a tracker that already exists."""

    tracker_id: Optional[str] = None
    name: str = ""
    notes: str = ""


class RejectRequest(BaseModel):
    notes: str = ""


def _ok(fn, *args, **kwargs):
    """A business rule becomes a 400 carrying its own message.

    An item that is not the caller's — or not there at all — is a 404, the way
    Composer answers it. Left unmapped, a `KeyError` escaped as a 500, which reads
    as "we broke" rather than "that is not yours".
    """
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="That proposal no longer exists.")


@router.post("/targets")
def build_targets(req: TargetsRequest, user: dict = Depends(require_authed)):
    """Propose a target list for a tracker, and queue it for a decision.

    Returns the proposal and, when it could be queued, the review item. A run that
    produced nothing is reported rather than queued — an empty review item asks
    somebody to decide about nothing.
    """
    analysis = {
        "vertical": req.vertical or "",
        "seed_company": req.seed_company or "",
        "notes": req.notes or "",
    }
    result = agent.build_targets(
        user["username"], analysis, req.config, use_signals=req.use_signals
    )

    review_item = None
    if req.submit_for_review and result["final"]["rows"]:
        review_item = review.submit(user["username"], result["final"], analysis)

    return {**result, "review": review_item}


@router.get("/targets/pending")
def pending_targets(user: dict = Depends(require_authed)):
    """Proposed lists still waiting on a decision."""
    return {"pending": review.pending(user["username"])}


@router.post("/targets/{item_id}/approve")
def approve_targets(item_id: str, req: ApproveRequest, user: dict = Depends(require_authed)):
    """Approve a proposal, which is what puts its accounts on a tracker."""
    return _ok(
        review.approve, item_id, user["username"],
        tracker_id=req.tracker_id, name=req.name, notes=req.notes,
    )


@router.post("/targets/{item_id}/retry")
def retry_targets(item_id: str, user: dict = Depends(require_authed)):
    """Put an approved list's accounts on its tracker again.

    The counterpart of Composer's `/draft-again`: the decision stands and cannot be
    retaken, so when only the landing failed, only the landing is retried.
    """
    return _ok(review.land_again, item_id, user["username"])


@router.post("/targets/{item_id}/reject")
def reject_targets(item_id: str, req: RejectRequest, user: dict = Depends(require_authed)):
    """Reject a proposal. It and the reason are kept."""
    return _ok(review.reject, item_id, user["username"], notes=req.notes)
