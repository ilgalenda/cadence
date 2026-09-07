"""The acceptance bar for GTM's four endpoints — the seam nothing covered.

`tests/test_gtm_targets.py` drives `review.approve`/`reject` directly and proves
the state machine. Nothing exercised the HTTP layer on top of it, and that layer
is where two of the defects lived:

  * **A proposal belongs to whoever asked for it.** `GET /targets/pending` filtered
    by submitter while `POST .../approve` did not, so a list one person read could
    be approved by another. Until a customer register exists this queue *is* the
    exclusion check, which makes "who read the names" the entire control.
  * **A missing item is a 404, not a 500.** `_ok` mapped `ValueError` and nothing
    else, so an unknown or unowned id escaped as a server error — "we broke"
    rather than "that is not yours".

And the endpoint that did not exist: `/retry`, the counterpart of Composer's
`/draft-again`, for a decision that stands while the landing failed.

`DATA_ROOT` is a throwaway directory and both stores are redirected at `tmp_path`,
so no test can reach real state.
"""
import base64
import json
import os
import tempfile

import itsdangerous
import pytest

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "gtm-route-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

_SECRET = os.environ["SESSION_SECRET"]

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from agents.outbound import db, valuation  # noqa: E402
from agents.sales.gtm import review  # noqa: E402

SAM = "gtm-route-sam"
OTHER = "gtm-route-other"

PROFILES = {
    SAM: {"username": SAM, "name": "Sam", "access": "user", "agents": []},
    OTHER: {"username": OTHER, "name": "Someone Else", "access": "user", "agents": []},
}

CATALOGUE = {
    "currency": "GBP",
    "shapes": {"primary_quorum": {"composition": "3x", "price_gbp": 1000, "enterprise_grade": True}},
    "support": {"standard_gbp_per_year": 500},
}

ROW = {
    "account": "Meridian Towers",
    "domain": "meridian.com",
    "segment": "Neutral host",
    "tier": 1,
    "campaign": "B-tdd",
    "geography": "Spain/EU",
    "target_roles": "Group CTO",
    "confidence": "high",
    "trigger_text": "",
    "trigger_source": "",
    "deal_lines": [{"shape": "primary_quorum", "quantity": 1}],
    "attach_support": True,
    "deal_rationale": "Multi-country framework.",
    "check": "Whether the estate carries its own sync today.",
    "caveat": "",
}

TARGETS = "/api/sales/gtm/targets"


def _session_cookie(user: str) -> str:
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(_SECRET).sign(payload).decode()


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "outbound.db")
    db.init_db()
    monkeypatch.setattr(valuation, "load_catalogue", lambda path=None: CATALOGUE)
    monkeypatch.setattr(review, "REVIEW_FILE", tmp_path / "tracker_review.json")


@pytest.fixture(autouse=True)
def known_users(monkeypatch):
    monkeypatch.setattr(auth, "find_user", lambda username: PROFILES.get(username))


@pytest.fixture()
def client():
    return TestClient(main.app)


def as_(client: TestClient, user: str) -> TestClient:
    """Sign the client in, the way `test_outbound_routes.py` does.

    The cookie is `cadence_session` — the name `SessionMiddleware` is configured
    with in `main.py`. Set on the client rather than per request, which httpx
    deprecates.
    """
    client.cookies.set("cadence_session", _session_cookie(user))
    return client


def _queued(user: str = SAM) -> str:
    """A proposal waiting on a decision, put there the way the agent puts it."""
    return review.submit(user, {"rows": [ROW], "notes": ""}, {"vertical": "neutral host"})["id"]


class TestWhoMayDecide:
    def test_pending_shows_only_your_own(self, client):
        mine = _queued(SAM)
        _queued(OTHER)

        listed = as_(client, SAM).get(f"{TARGETS}/pending").json()["pending"]
        assert [item["id"] for item in listed] == [mine]

    @pytest.mark.parametrize("action, body", [
        ("approve", {}),
        ("reject", {"notes": "not ours"}),
        ("retry", None),
    ])
    def test_another_persons_proposal_is_not_there(self, client, action, body):
        theirs = _queued(OTHER)

        res = as_(client, SAM).post(f"{TARGETS}/{theirs}/{action}", json=body)

        # 404 rather than 403: a refusal would confirm the id exists.
        assert res.status_code == 404, res.text
        assert review.queue().get(theirs).status == "pending"

    def test_an_id_that_never_existed_answers_the_same_way(self, client):
        res = as_(client, SAM).post(f"{TARGETS}/nonexistent/approve", json={})
        assert res.status_code == 404

    def test_signing_in_is_required(self, client):
        # Not signed in: no cookie is set on this client at all.
        assert client.get(f"{TARGETS}/pending").status_code == 401


class TestApproving:
    def test_approving_lands_the_accounts_and_reports_them(self, client):
        item = _queued()

        res = as_(client, SAM).post(f"{TARGETS}/{item}/approve", json={})

        assert res.status_code == 200, res.text
        out = res.json()
        assert out["added"] == ["Meridian Towers"]
        assert out["tracker_error"] is None
        assert out["tracker"]["name"] == "Outbound · neutral host"

    def test_a_tracker_that_does_not_exist_is_a_400_and_costs_the_proposal_nothing(self, client):
        item = _queued()
        signed_in = as_(client, SAM)

        res = signed_in.post(f"{TARGETS}/{item}/approve", json={"tracker_id": "nonexistent"})

        assert res.status_code == 400
        assert "No such tracker" in res.json()["detail"]
        # Still decidable — the whole reason the tracker is resolved first.
        assert review.queue().get(item).status == "pending"
        assert signed_in.post(f"{TARGETS}/{item}/approve", json={}).status_code == 200

    def test_a_decision_cannot_be_retaken(self, client):
        item = _queued()
        signed_in = as_(client, SAM)
        assert signed_in.post(f"{TARGETS}/{item}/approve", json={}).status_code == 200

        again = signed_in.post(f"{TARGETS}/{item}/approve", json={})
        assert again.status_code == 400


class TestRetrying:
    def test_a_list_that_did_not_land_can_be_landed_again(self, client, monkeypatch):
        from agents.outbound import store as outbound_store

        item = _queued()
        # Fails once, then behaves — the shape of a row the store refused until
        # somebody fixed it. Restoring by hand rather than `monkeypatch.undo()`,
        # which would also lift the autouse fixtures' patches.
        real = outbound_store.add_rows
        first = []

        def once(*args, **kwargs):
            if not first:
                first.append(True)
                raise ValueError("Meridian Towers: tier must be 1, 2 or 3, not 9.")
            return real(*args, **kwargs)

        monkeypatch.setattr(outbound_store, "add_rows", once)

        failed = as_(client, SAM).post(f"{TARGETS}/{item}/approve", json={}).json()
        assert failed["tracker_error"] and "tier" in failed["tracker_error"]
        assert failed["added"] == []

        out = as_(client, SAM).post(f"{TARGETS}/{item}/retry")

        assert out.status_code == 200, out.text
        assert out.json()["added"] == ["Meridian Towers"]
        assert out.json()["tracker_error"] is None

    def test_retrying_a_list_nobody_has_decided_is_refused(self, client):
        item = _queued()
        res = as_(client, SAM).post(f"{TARGETS}/{item}/retry")
        assert res.status_code == 400
        assert "approved" in res.json()["detail"]


class TestRejecting:
    def test_rejecting_keeps_the_list_and_the_reason(self, client):
        item = _queued()

        res = as_(client, SAM).post(f"{TARGETS}/{item}/reject",
                          json={"notes": "three of these are customers"})

        assert res.status_code == 200, res.text
        stored = review.queue().get(item)
        assert stored.status == "rejected"
        assert stored.review_notes == "three of these are customers"
        assert stored.payload["accounts"] == ["Meridian Towers"]
