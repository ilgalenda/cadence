"""Tests for the Review/Approval gate primitive (agents.services.review)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.services import review  # noqa: E402
from agents.services.review import ReviewQueue  # noqa: E402


@pytest.fixture
def queue(tmp_path):
    return ReviewQueue(tmp_path / "queue.json")


def _draft(q, kind="outreach_email", by="composer-agent"):
    return q.submit(kind=kind, payload={"subject": "Hi", "body": "…"}, submitted_by=by)


def test_submit_starts_pending_with_audit(queue):
    item = _draft(queue)
    assert item.status == review.PENDING
    assert item.is_pending
    assert item.id
    assert item.reviewed_by is None
    assert item.history == [
        {"status": "pending", "by": "composer-agent", "at": item.created_at, "notes": ""}
    ]


def test_submit_requires_kind_and_submitter(queue):
    with pytest.raises(ValueError):
        queue.submit(kind="", payload={}, submitted_by="agent")
    with pytest.raises(ValueError):
        queue.submit(kind="x", payload={}, submitted_by="")


def test_approve_stamps_reviewer_and_appends_history(queue):
    item = _draft(queue)
    approved = queue.approve(item.id, reviewed_by="sam", notes="looks good")
    assert approved.status == review.APPROVED
    assert approved.reviewed_by == "sam"
    assert approved.reviewed_at
    assert approved.review_notes == "looks good"
    assert [h["status"] for h in approved.history] == ["pending", "approved"]
    assert not approved.is_pending


def test_reject_moves_to_rejected(queue):
    item = _draft(queue)
    rejected = queue.reject(item.id, reviewed_by="sam", notes="wrong angle")
    assert rejected.status == review.REJECTED
    assert [h["status"] for h in rejected.history] == ["pending", "rejected"]


def test_terminal_decisions_are_immutable(queue):
    item = _draft(queue)
    queue.approve(item.id, reviewed_by="sam")
    # An approved item cannot be re-decided — no silent rewrite of a decision.
    with pytest.raises(ValueError):
        queue.approve(item.id, reviewed_by="sam")
    with pytest.raises(ValueError):
        queue.reject(item.id, reviewed_by="sam")


def test_decision_requires_a_human_reviewer(queue):
    item = _draft(queue)
    with pytest.raises(ValueError):
        queue.approve(item.id, reviewed_by="")


def test_decide_unknown_item_raises(queue):
    with pytest.raises(KeyError):
        queue.approve("does-not-exist", reviewed_by="sam")


def test_get_returns_none_for_unknown(queue):
    assert queue.get("nope") is None


def test_list_filters_and_orders_newest_first(queue):
    a = _draft(queue, kind="outreach_email", by="composer")
    b = _draft(queue, kind="target_list", by="gtm")
    c = _draft(queue, kind="outreach_email", by="composer")
    queue.approve(b.id, reviewed_by="sam")

    ids_newest_first = [i.id for i in queue.list()]
    assert ids_newest_first[0] == c.id and ids_newest_first[-1] == a.id

    assert {i.id for i in queue.list(kind="outreach_email")} == {a.id, c.id}
    assert [i.id for i in queue.pending(kind="outreach_email")] == [c.id, a.id]
    assert {i.id for i in queue.list(status=review.APPROVED)} == {b.id}
    assert {i.id for i in queue.list(submitted_by="gtm")} == {b.id}


def test_persistence_round_trips_across_instances(queue, tmp_path):
    item = _draft(queue)
    queue.approve(item.id, reviewed_by="sam", notes="ship")
    # A fresh queue over the same file sees the persisted decision.
    reopened = ReviewQueue(tmp_path / "queue.json")
    got = reopened.get(item.id)
    assert got is not None
    assert got.status == review.APPROVED
    assert got.review_notes == "ship"


def test_no_agent_facing_send_or_execute_action(queue):
    # The "agents draft, human sends" rule is structural: the gate exposes no
    # way for an agent to send/execute/action an item — only submit + the
    # human-owned approve/reject.
    forbidden = {"send", "execute", "action", "dispatch", "fire", "commit"}
    assert forbidden.isdisjoint(dir(queue))
