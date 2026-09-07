"""The acceptance bar for the outbound surface — the scope and the watch cap.

Three things are worth proving at the HTTP layer, because none is visible in the
store:

  * **A tracker is one person's list.** The scope is a predicate on the reads *and*
    the writes, and somebody else's tracker answers "No such tracker" rather than
    refusing — a refusal leaks that it exists. An admin sees every tracker.
  * **Watching a long tracker does not half-fail.** The Signals watchlist is capped
    at fifty accounts because each one costs a search per sweep. A tracker larger
    than the headroom watches as far as it goes and *reports* the rest; it never
    watches some accounts and then raises.
  * **A business rule reaches the page as a 400 with its own message**, not a 500.

`DATA_ROOT` is a throwaway directory and both databases are redirected at
`tmp_path`, so no test can reach real state — including the developer's real
watchlist.
"""
import base64
import json
import os
import tempfile

import itsdangerous
import pytest

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "outbound-route-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

_SECRET = os.environ["SESSION_SECRET"]

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from agents.outbound import db, store, valuation  # noqa: E402
from agents.sales.store import signals as signals_store  # noqa: E402

SAM = "outbound-test-sam"
OTHER = "outbound-test-other"
ADMIN = "outbound-test-admin"

PROFILES = {
    SAM: {"username": SAM, "name": "Sam", "access": "user", "agents": []},
    OTHER: {"username": OTHER, "name": "Someone Else", "access": "user", "agents": []},
    ADMIN: {"username": ADMIN, "name": "Admin", "access": "admin", "agents": []},
}

CATALOGUE = {
    "currency": "GBP",
    "shapes": {"primary_quorum": {"composition": "3x", "price_gbp": 1000, "enterprise_grade": True}},
    "support": {"standard_gbp_per_year": 500},
}

MERIDIAN = {
    "account": "Meridian Towers",
    "segment": "Neutral host",
    "tier": 1,
    "campaign": "B-tdd",
    "geography": "Spain/EU",
    "confidence": "high",
    "deal_lines": [{"shape": "primary_quorum"}],
    "attach_support": True,
}


def _session_cookie(user: str) -> str:
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(_SECRET).sign(payload).decode()


@pytest.fixture(autouse=True)
def outbound_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "outbound.db")
    db.init_db()
    monkeypatch.setattr(valuation, "load_catalogue", lambda path=None: CATALOGUE)


@pytest.fixture(autouse=True)
def isolated_watchlist(tmp_path, monkeypatch):
    """No test may read or write the developer's real Signals watchlist."""
    monkeypatch.setattr(signals_store, "WATCHLIST_FILE", tmp_path / "watchlist.json")


@pytest.fixture(autouse=True)
def known_users(monkeypatch):
    monkeypatch.setattr(auth, "find_user", lambda username: PROFILES.get(username))


@pytest.fixture()
def client():
    return TestClient(main.app)


def as_(client: TestClient, user: str):
    """Sign the client in as one of the test people.

    The cookie is `cadence_session` — the name `SessionMiddleware` is configured
    with in `main.py`. A plain `session` cookie authenticates nobody, which shows
    up as a 401 on every assertion rather than as an auth failure.
    """
    client.cookies.set("cadence_session", _session_cookie(user))
    return client


@pytest.fixture()
def sams_tracker():
    return store.create_tracker("Q4 outbound", SAM, goal_gbp=100000, target_touches=750)


# ---------------------------------------------------------------------------
# A tracker is one person's list
# ---------------------------------------------------------------------------

def test_signing_in_is_required(client):
    assert client.get("/api/outbound/trackers").status_code == 401


def test_a_person_sees_only_their_own_trackers(client, sams_tracker):
    store.create_tracker("Somebody else's", OTHER)
    body = as_(client, SAM).get("/api/outbound/trackers").json()
    assert [t["name"] for t in body["trackers"]] == ["Q4 outbound"]


def test_an_admin_sees_every_tracker(client, sams_tracker):
    store.create_tracker("Somebody else's", OTHER)
    body = as_(client, ADMIN).get("/api/outbound/trackers").json()
    assert len(body["trackers"]) == 2


def test_somebody_elses_tracker_says_no_such_tracker(client, sams_tracker):
    """Not a 403 — a refusal would confirm it exists."""
    response = as_(client, OTHER).get(f"/api/outbound/trackers/{sams_tracker['id']}")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such tracker"


def test_the_scope_covers_writes_as_well_as_reads(client, sams_tracker):
    response = as_(client, OTHER).post(
        f"/api/outbound/trackers/{sams_tracker['id']}/rows", json={"rows": [MERIDIAN]}
    )
    assert response.status_code == 404
    assert store.get_rows(sams_tracker["id"]) == []


def test_a_row_is_unreachable_through_its_tracker(client, sams_tracker):
    store.add_rows(sams_tracker["id"], [MERIDIAN], actor=SAM)
    row = store.get_rows(sams_tracker["id"])[0]

    response = as_(client, OTHER).post(
        f"/api/outbound/rows/{row['id']}/status", json={"status": "dead"}
    )
    assert response.status_code == 404
    assert store.get_row(row["id"])["status"] == "not_started"


# ---------------------------------------------------------------------------
# The record, end to end
# ---------------------------------------------------------------------------

def test_a_tracker_is_created_filled_and_read_back(client):
    session = as_(client, SAM)

    tracker = session.post(
        "/api/outbound/trackers",
        json={"name": "Q4 outbound", "goal_gbp": 100000, "target_touches": 750,
              "target_qualified": 6},
    ).json()

    session.post(f"/api/outbound/trackers/{tracker['id']}/rows", json={"rows": [MERIDIAN]})
    body = session.get(f"/api/outbound/trackers/{tracker['id']}").json()

    assert body["counters"]["targets"] == 1
    assert body["counters"]["target_qualified"] == 6
    assert body["rows"][0]["value_est_gbp"] == 1500
    assert [t["fired"] for t in body["rows"][0]["touches"]] == [False] * 5


def test_firing_a_touch_moves_the_counters(client, sams_tracker):
    session = as_(client, SAM)
    session.post(f"/api/outbound/trackers/{sams_tracker['id']}/rows", json={"rows": [MERIDIAN]})
    row = store.get_rows(sams_tracker["id"])[0]

    updated = session.post(f"/api/outbound/rows/{row['id']}/touch", json={"index": 1}).json()
    assert updated["status"] == "sequencing"

    counters = session.get(f"/api/outbound/trackers/{sams_tracker['id']}").json()["counters"]
    assert (counters["touches"], counters["in_sequence"]) == (1, 1)


def test_the_artifact_url_is_recorded(client, sams_tracker):
    session = as_(client, SAM)
    session.put(
        f"/api/outbound/trackers/{sams_tracker['id']}/artifact",
        json={"url": "https://claude.ai/code/artifact/abc"},
    )
    body = session.get(f"/api/outbound/trackers/{sams_tracker['id']}").json()
    assert body["tracker"]["artifact_url"].endswith("abc")


# ---------------------------------------------------------------------------
# Business rules arrive as 400s
# ---------------------------------------------------------------------------

def test_a_bad_tier_is_a_400_carrying_its_own_message(client, sams_tracker):
    response = as_(client, SAM).post(
        f"/api/outbound/trackers/{sams_tracker['id']}/rows",
        json={"rows": [{**MERIDIAN, "tier": 9}]},
    )
    assert response.status_code == 400
    assert "tier must be" in response.json()["detail"]


def test_an_unknown_status_is_a_400(client, sams_tracker):
    session = as_(client, SAM)
    session.post(f"/api/outbound/trackers/{sams_tracker['id']}/rows", json={"rows": [MERIDIAN]})
    row = store.get_rows(sams_tracker["id"])[0]

    response = session.post(f"/api/outbound/rows/{row['id']}/status", json={"status": "warm"})
    assert response.status_code == 400
    assert "is not a status" in response.json()["detail"]


def test_editing_a_field_a_person_does_not_own_is_a_400(client, sams_tracker):
    session = as_(client, SAM)
    session.post(f"/api/outbound/trackers/{sams_tracker['id']}/rows", json={"rows": [MERIDIAN]})
    row = store.get_rows(sams_tracker["id"])[0]

    response = session.patch(f"/api/outbound/rows/{row['id']}", json={"changes": {"tier": 2}})
    assert response.status_code == 400
    assert "cannot be edited here" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The watch cap
# ---------------------------------------------------------------------------

def test_watching_a_tracker_puts_its_accounts_on_the_watchlist(client, sams_tracker):
    session = as_(client, SAM)
    session.post(
        f"/api/outbound/trackers/{sams_tracker['id']}/rows",
        json={"rows": [MERIDIAN, {**MERIDIAN, "account": "Corvus Radio"}]},
    )

    body = session.post(f"/api/outbound/trackers/{sams_tracker['id']}/watch").json()
    assert body["count"] == 2
    assert body["refused"] == []
    assert {e["company"] for e in signals_store.watchlist(SAM)} == {"Meridian Towers", "Corvus Radio"}


def test_a_tracker_longer_than_the_cap_watches_what_it_can_and_reports_the_rest(
    client, sams_tracker
):
    """Never watch some and then raise — a half-applied call is the worst outcome."""
    session = as_(client, SAM)
    accounts = [{**MERIDIAN, "account": f"Account {n:03d}"} for n in range(signals_store.MAX_WATCHED + 5)]
    session.post(f"/api/outbound/trackers/{sams_tracker['id']}/rows", json={"rows": accounts})

    response = session.post(f"/api/outbound/trackers/{sams_tracker['id']}/watch")
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == signals_store.MAX_WATCHED
    assert len(body["refused"]) == 5
    assert str(signals_store.MAX_WATCHED) in body["refused"][0]["why"]


# ---------------------------------------------------------------------------
# Deleting a campaign
# ---------------------------------------------------------------------------

def test_a_person_can_delete_their_own_campaign(client, sams_tracker):
    session = as_(client, SAM)
    session.post(f"/api/outbound/trackers/{sams_tracker['id']}/rows", json={"rows": [MERIDIAN]})

    response = session.delete(f"/api/outbound/trackers/{sams_tracker['id']}")

    assert response.status_code == 200
    assert response.json()["accounts"] == 1
    assert store.get_tracker(sams_tracker["id"]) is None


def test_somebody_else_cannot_delete_a_campaign(client, sams_tracker):
    """A 404, not a 403 — the same rule as every other read and write here."""
    response = as_(client, OTHER).delete(f"/api/outbound/trackers/{sams_tracker['id']}")

    assert response.status_code == 404
    assert store.get_tracker(sams_tracker["id"]) is not None


def test_deleting_needs_a_session(client, sams_tracker):
    assert client.delete(f"/api/outbound/trackers/{sams_tracker['id']}").status_code == 401
    assert store.get_tracker(sams_tracker["id"]) is not None


def test_deleting_a_campaign_twice_is_a_404_the_second_time(client, sams_tracker):
    session = as_(client, SAM)
    assert session.delete(f"/api/outbound/trackers/{sams_tracker['id']}").status_code == 200
    assert session.delete(f"/api/outbound/trackers/{sams_tracker['id']}").status_code == 404
