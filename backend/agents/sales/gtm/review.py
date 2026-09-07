"""The gate between a proposed target list and a tracker that exists.

`build_targets` writes nothing. It submits, and a person decides — the platform
rule `agents/services/review.py` enforces structurally, and the queue was already
built for exactly this: its docstring names "a target list" and
`tests/test_review.py` has exercised `kind="target_list", by="gtm"` since before
this module existed. Nothing in production had ever used it.

**Why the gate matters more here than anywhere else.** The brain holds no customer
list. Three existing clients have already reached a "net-new" target list and each
was caught by a person reading the names — so until a customer register exists,
this queue *is* the exclusion check. That is a weak control resting on
recognition, and it is recorded as such rather than dressed up.

Approving is what creates the tracker. Rejecting keeps the proposal and its reason,
because why a list was thrown away is worth as much as why one was kept.
"""
from __future__ import annotations

from typing import Optional

from paths import outbound_data

from agents.outbound import store as outbound_store
from agents.services.review import ReviewQueue

#: One file per install, filtered per user on read — the convention every sales
#: store follows. It lives beside the tracker database rather than with the sales
#: stores, because what it queues is a tracker.
REVIEW_FILE = outbound_data() / "tracker_review.json"

KIND = "target_list"


def queue() -> ReviewQueue:
    return ReviewQueue(REVIEW_FILE)


def submit(username: str, proposal: dict, request: dict) -> dict:
    """Put a proposed list in front of a person. Returns the queued item.

    The request is stored with the proposal so a list can be read against what was
    asked for. A list of twelve defence accounts is right or wrong depending on
    whether somebody asked for defence, and that question cannot be answered from
    the list alone.
    """
    rows = (proposal or {}).get("rows") or []
    if not rows:
        raise ValueError("There is nothing to review — the proposal has no accounts.")

    return queue().submit(
        kind=KIND,
        submitted_by=username,
        payload={
            "request": request,
            "notes": (proposal or {}).get("notes") or "",
            "rows": rows,
            "accounts": [row.get("account") for row in rows],
        },
    ).to_dict()


def pending(username: Optional[str] = None) -> list[dict]:
    """Proposals still waiting on a decision, newest first."""
    return [item.to_dict() for item in queue().pending(kind=KIND, submitted_by=username)]


def _mine(item_id: str, username: str):
    """The caller's own pending-or-decided item, or `KeyError`.

    An item belonging to somebody else is reported as one that does not exist. The
    approve route never made this check while `pending()` filtered by submitter, so
    a list could be read by one person and approved by another — and this queue is
    the only exclusion check the platform has, which makes "who read it" the whole
    control. Composer and Recap have always checked; this did not.
    """
    item = queue().get(item_id)
    if item is None or item.kind != KIND or item.submitted_by != username:
        raise KeyError(item_id)
    return item


def approve(item_id: str, username: str, *, tracker_id: Optional[str] = None,
            name: str = "", notes: str = "") -> dict:
    """Approve a proposal and put its accounts on a tracker.

    A new tracker is created unless one is named, in which case the accounts join
    it. Joining is the common case after the first list: a second proposal for the
    same campaign should extend the list somebody is working, not start a rival
    one — and `add_rows` leaves an account already there alone, so the state built
    against it survives.

    The tracker id and what landed are recorded as the item's **outcome**, which is
    a fact discovered after the decision rather than part of it.

    **The order is the whole design, and it used to be wrong.** The decision was
    recorded first, and four things between it and the outcome could raise — an
    unknown tracker, a blank name, a row the store refuses, the outcome write
    itself. A terminal decision is immutable by design (`_ALLOWED_TRANSITIONS` has
    no edge out of `approved`), so any of them left the item approved with nothing
    landed and no way back to `pending`: recovery meant re-running the whole model
    call. So the work is split by whether it is entitled to refuse:

    * **Resolving the tracker may refuse, so it happens first.** A bad `tracker_id`
      must never produce an approval.
    * **Landing the rows may not.** They are re-inflated from disk and were last
      validated when they were queued, so a vocabulary that has moved since can
      raise mid-list. That is caught, recorded as `tracker_error`, and retried
      through `land_again` — the shape Composer uses for a Gmail draft that fails
      after an approval it must not undo.
    """
    item = _mine(item_id, username)

    # Before the decision: this is allowed to refuse, and must.
    if tracker_id:
        tracker = outbound_store.get_tracker(tracker_id)
        if not tracker:
            raise ValueError("No such tracker")
    else:
        tracker = outbound_store.create_tracker(
            name or _default_name(item), username, **_GOALS
        )

    decided = queue().approve(item_id, reviewed_by=username, notes=notes)
    return {"tracker": tracker, **_land(decided, tracker, username)}


def land_again(item_id: str, username: str) -> dict:
    """Retry landing an approved list whose rows did not make it onto the tracker.

    Needed because the queue refuses to re-decide a terminal item — correctly, the
    decision has not changed. Only the landing failed, so only it is retried, and
    `record_outcome` merges, so a success cleanly replaces the recorded error.
    """
    item = _mine(item_id, username)
    if item.status != "approved":
        raise ValueError("Only an approved list has accounts waiting to land.")

    tracker_id = (item.outcome or {}).get("tracker_id")
    tracker = outbound_store.get_tracker(tracker_id) if tracker_id else None
    if not tracker:
        raise ValueError("No such tracker")

    return {"tracker": tracker, **_land(item, tracker, username)}


def _land(item, tracker: dict, username: str) -> dict:
    """Put the item's rows on the tracker and record what happened. Never raises.

    Always records an outcome, success or failure — an approval that is on disk
    with no record of what followed is the state this whole ordering exists to
    prevent.
    """
    rows = item.payload.get("rows") or []
    try:
        landed = outbound_store.add_rows(
            tracker["id"], [dict(row) for row in rows], actor=username
        )
    except Exception as e:  # noqa: BLE001 — a decision must survive anything
        outcome = {
            "tracker_id": tracker["id"],
            "added": [],
            "already_there": [],
            "tracker_error": f"The accounts could not be put on the tracker: {e}",
        }
    else:
        outcome = {
            "tracker_id": tracker["id"],
            "added": [row["account"] for row in landed["added"]],
            "already_there": landed["skipped"],
            "tracker_error": None,
        }

    queue().record_outcome(item.id, outcome=outcome)
    return outcome


def reject(item_id: str, username: str, notes: str = "") -> dict:
    """Reject a proposal, keeping it and the reason."""
    _mine(item_id, username)
    return queue().reject(item_id, reviewed_by=username, notes=notes).to_dict()


#: The goals a new tracker is measured against. They are properties of the Q4
#: plan rather than of any account, and they are here rather than asked for
#: because a tracker created with zeroes reports progress against nothing.
_GOALS = {
    "goal_gbp": 100_000,
    "target_touches": 750,
    "target_replies": 35,
    "target_calls": 20,
    "target_qualified": 6,
}


def _default_name(item) -> str:
    """A name from what was asked for, so two trackers are told apart."""
    request = item.payload.get("request") or {}
    scope = (request.get("vertical") or request.get("seed_company") or "").strip()
    return f"Outbound · {scope}" if scope else "Outbound"
