"""Route-level tests for what a call put into the vault — `/api/sales/calls`.

The reverse of a page's sources. The rules the frontend depends on:

  * a call reports its terms and its learnings in one list, because "what did
    this call teach us" is one question;
  * a learning says `wiki_slug: null` rather than being hidden — it is still
    something the call taught, it simply has no wiki page;
  * another user's call id is a 404, in the same words as the rest of the module;
  * the library index carries what actually reached the vault, which is not the
    same number as what the model proposed.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile

import itsdangerous
import pytest

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "call-knowledge-test-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agents.sales.call_analysis import routes as call_routes  # noqa: E402
from agents.shared import sources  # noqa: E402
from auth import require_authed  # noqa: E402

USER = "calls-test-user"

SESSION = {
    "id": "call-1",
    "title": "Datacentre operator — holdover",
    "type": "call_analysis",
    "timestamp": "24 Jul 2026, 13:57",
    "username": USER,
    "result": {
        "summary": "They need 24h holdover.",
        "knowledge_extracts": [{"title": "Holdover", "content": "…", "description": "…"}],
        "new_terms": [{"term": "Holdover", "definition": "…"}, {"term": "Unknown Thing"}],
        "buying_signals": ["budget approved"],
        "objections": [],
    },
}

PAGES = [
    sources.KnowledgePage(
        key="glossary/holdover", title="Holdover", type="glossary",
        summary="How long a clock keeps time.", wiki_slug="glossary/holdover",
        contributed_by=USER, captured_at="2026-07-24T14:00:00+00:00",
    ),
    sources.KnowledgePage(
        key="learning/ccc1--holdover-is-the-trigger", title="Holdover is the trigger",
        type="learning", summary="A 24h requirement ruled out the incumbent.",
        wiki_slug=None, contributed_by=USER, captured_at="2026-07-24T13:57:00+00:00",
    ),
]


def _session_cookie(user: str = USER) -> str:
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(os.environ["SESSION_SECRET"]).sign(payload).decode()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        call_routes.store, "get_session",
        lambda call_id, username, sandbox=False: (
            SESSION if call_id == SESSION["id"] and username == USER else None
        ),
    )
    monkeypatch.setattr(
        call_routes.store, "load_user_sessions",
        lambda username, sandbox=False: [SESSION] if username == USER else [],
    )
    monkeypatch.setattr(
        call_routes.sources, "pages_from_call",
        lambda call_id: list(PAGES) if call_id == SESSION["id"] else [],
    )
    monkeypatch.setattr(call_routes.sources, "counts_by_call", lambda: {"call-1": 2})
    monkeypatch.setattr(
        call_routes.wiki, "resolve_link",
        lambda name: "glossary/holdover" if name == "Holdover" else None,
    )

    main.app.dependency_overrides[require_authed] = lambda: {"username": USER, "access": "user"}
    with TestClient(main.app, cookies={"cadence_session": _session_cookie()}) as c:
        yield c
    main.app.dependency_overrides.clear()


# --- what a call taught -----------------------------------------------------

def test_a_call_reports_terms_and_learnings_together(client):
    body = client.get("/api/sales/calls/call-1/knowledge").json()
    assert body["call_id"] == "call-1"
    assert body["total"] == 2
    assert [page["type"] for page in body["pages"]] == ["glossary", "learning"]


def test_a_learning_says_it_has_no_wiki_page(client):
    body = client.get("/api/sales/calls/call-1/knowledge").json()
    learning = next(page for page in body["pages"] if page["type"] == "learning")
    assert learning["wiki_slug"] is None
    assert learning["title"], "a page with nowhere to go still has to be named"


def test_another_users_call_is_not_readable(client):
    assert client.get("/api/sales/calls/somebody-elses/knowledge").status_code == 404


# --- terms know which page they became --------------------------------------

def test_a_term_is_told_the_page_it_can_be_read_on(client):
    result = client.get("/api/sales/calls/call-1").json()["result"]
    placed = {term["term"]: term["page_slug"] for term in result["new_terms"]}
    assert placed["Holdover"] == "glossary/holdover"


def test_a_term_the_wiki_cannot_place_gets_no_link(client):
    """Never an anchor to a page that does not exist."""
    result = client.get("/api/sales/calls/call-1").json()["result"]
    placed = {term["term"]: term["page_slug"] for term in result["new_terms"]}
    assert placed["Unknown Thing"] is None


def test_the_stored_reading_is_not_rewritten(client):
    """`page_slug` is a fact about the vault, not part of what the model said."""
    client.get("/api/sales/calls/call-1")
    assert "page_slug" not in SESSION["result"]["new_terms"][0]


# --- the library index ------------------------------------------------------

def test_a_library_row_reports_what_reached_the_vault(client):
    [row] = client.get("/api/sales/calls").json()
    assert row["knowledge"] == 2
    assert row["extracts"] == 1, "what the model proposed is a different number"


# --- product fit, the opt-in second pass ------------------------------------
#
# The page leaves the product field blank in the common case — "assess across
# the catalogue" — and the route's contract is `product_name: str = ""`. Sending
# anything that is not a string fails validation before the agent is reached, so
# the button could only report "failed — try again". There was no coverage here
# at all, which is why that went unnoticed.

def test_an_unnamed_product_assesses_the_whole_catalogue(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        call_routes.agent, "product_fit",
        lambda username, *, call_id, product_name, sandbox=False: seen.update(
            product_name=product_name
        ) or {"primary": "Open Time Appliance"},
    )

    res = client.post(f"/api/sales/calls/{SESSION['id']}/product-fit", json={"product_name": ""})

    assert res.status_code == 200
    assert seen["product_name"] == ""


def test_an_omitted_product_is_the_same_as_an_unnamed_one(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        call_routes.agent, "product_fit",
        lambda username, *, call_id, product_name, sandbox=False: seen.update(
            product_name=product_name
        ) or {"primary": "Open Time Appliance"},
    )

    res = client.post(f"/api/sales/calls/{SESSION['id']}/product-fit", json={})

    assert res.status_code == 200
    assert seen["product_name"] == ""


def test_a_named_product_reaches_the_agent(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        call_routes.agent, "product_fit",
        lambda username, *, call_id, product_name, sandbox=False: seen.update(
            product_name=product_name
        ) or {"primary": "Open Timecard"},
    )

    res = client.post(
        f"/api/sales/calls/{SESSION['id']}/product-fit",
        json={"product_name": "Open Timecard"},
    )

    assert res.status_code == 200
    assert seen["product_name"] == "Open Timecard"


def test_a_null_product_is_refused_rather_than_silently_meaning_nothing(client):
    """The contract is a string. `null` is a caller bug, and it must be loud."""
    res = client.post(
        f"/api/sales/calls/{SESSION['id']}/product-fit", json={"product_name": None}
    )

    assert res.status_code == 422
