"""The acceptance bar for X-ray's enrichment routes — the service/route seam.

This seam had no coverage, and that is exactly where it broke: the routes read
`full_name`/`company`/`job_title` off an `EnrichedContact`, which only ever
carried revealed contact details. Every *successful* enrichment raised
`AttributeError` outside the error boundary, so revealing an email was a 500 and
no shortlist ever carried an address. `tests/test_enrichment.py` covers the
service thoroughly; nothing covered the handler on top of it.

These tests drive the real `Enrichment` service through the HTTP layer with only
the Lusha client faked, so the identity join is exercised rather than mocked out.
"""
import base64
import json
import os
import tempfile

import itsdangerous
import pytest

# main.py reads these at import time, and another route-test module may have
# imported it already — so these are defaults, never overwrites, and the cookie
# below is signed with whatever secret the app actually loaded. Setting our own
# unconditionally would leave the suite's result dependent on file order.
# DATA_ROOT points at a throwaway directory so no test can reach real state.
os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "xray-enrich-route-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

_SECRET = os.environ["SESSION_SECRET"]

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agents.services import enrichment  # noqa: E402
from auth import require_authed  # noqa: E402

USER = "xray-enrich-test-user"

# Two people whose names would defeat a name-based join: one is abbreviated the
# way a LinkedIn display name often is, and both share a surname initial.
PEOPLE = [
    {"full_name": "Ada Lovelace", "company": "Acme", "job_title": "Head of Infrastructure"},
    {"full_name": "Alan T.", "company": "Acme", "job_title": "Network Architect"},
]


def _session_cookie(user: str = USER) -> str:
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(_SECRET).sign(payload).decode()


class _FakeLusha:
    """Stands in for the provider. Records calls; returns a canned envelope."""

    def __init__(self, response: dict):
        self._response = response
        self.calls: list[dict] = []

    def enrich(self, contacts, *, reveal_emails: bool, reveal_phones: bool) -> dict:
        self.calls.append(
            {"contacts": contacts, "reveal_emails": reveal_emails, "reveal_phones": reveal_phones}
        )
        return self._response


@pytest.fixture
def client():
    main.app.dependency_overrides[require_authed] = lambda: {"username": USER, "access": "admin"}
    with TestClient(main.app, cookies={"cadence_session": _session_cookie()}) as c:
        yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def fake_lusha(monkeypatch):
    """Install a provider whose response the test chooses."""

    def install(response: dict) -> _FakeLusha:
        provider = _FakeLusha(response)
        monkeypatch.setattr(enrichment, "LushaClient", lambda *a, **k: provider)
        return provider

    return install


# --- /enrich ---------------------------------------------------------------

def test_enrich_places_each_email_on_the_person_it_belongs_to(client, fake_lusha):
    """The regression that matters: emails must not shuffle between rows.

    The provider answers out of order and keys by the `contactId` we supplied,
    so a handler that trusted response order would swap these two people.
    """
    fake_lusha({
        "error": None,
        "contacts": {
            "1": {"emailAddresses": [{"email": "alan@acme.com"}]},
            "0": {"emailAddresses": [{"email": "ada@acme.com"}]},
        },
    })

    res = client.post("/api/sales/xray/enrich", json={"people": PEOPLE})
    assert res.status_code == 200

    rows = res.json()
    assert [r["full_name"] for r in rows] == ["Ada Lovelace", "Alan T."]
    assert [r["email"] for r in rows] == ["ada@acme.com", "alan@acme.com"]
    # The index is what lets the page target a row without matching on name.
    assert [r["index"] for r in rows] == [0, 1]


def test_enrich_returns_identity_from_the_request_not_the_provider(client, fake_lusha):
    """Identity is ours; the provider only supplies contact details.

    Its record carries a differently-formatted name, which must not overwrite
    the row the user is looking at.
    """
    fake_lusha({
        "error": None,
        "contacts": {"0": {"fullName": "LOVELACE, ADA", "emailAddresses": [{"email": "ada@acme.com"}]}},
    })

    row = client.post("/api/sales/xray/enrich", json={"people": [PEOPLE[0]]}).json()[0]
    assert row["full_name"] == "Ada Lovelace"
    assert row["company"] == "Acme"
    assert row["job_title"] == "Head of Infrastructure"
    assert row["email"] == "ada@acme.com"


def test_enrich_reports_a_person_with_nothing_on_file(client, fake_lusha):
    """A miss is an outcome, not an omission — the row still comes back.

    Dropping unmatched people would silently shorten the response and leave the
    page unable to tell "no email exists" from "we forgot to ask".
    """
    fake_lusha({"error": None, "contacts": {"0": {"emailAddresses": [{"email": "ada@acme.com"}]}}})

    rows = client.post("/api/sales/xray/enrich", json={"people": PEOPLE}).json()
    assert len(rows) == 2
    assert rows[0]["email"] == "ada@acme.com"
    assert rows[1]["email"] is None
    assert rows[1]["full_name"] == "Alan T."


def test_enrich_spends_one_bulk_call_and_never_asks_for_phones(client, fake_lusha):
    """Credit discipline: email is bulk and automatic, phone never a side effect."""
    provider = fake_lusha({"error": None, "contacts": {}})

    client.post("/api/sales/xray/enrich", json={"people": PEOPLE})
    assert len(provider.calls) == 1
    assert provider.calls[0]["reveal_emails"] is True
    assert provider.calls[0]["reveal_phones"] is False
    assert len(provider.calls[0]["contacts"]) == 2


def test_enrich_rejects_an_empty_selection_without_spending(client, fake_lusha):
    provider = fake_lusha({"error": None, "contacts": {}})

    res = client.post("/api/sales/xray/enrich", json={"people": []})
    assert res.status_code == 400
    assert provider.calls == []


def test_enrich_surfaces_a_provider_failure_as_502(client, monkeypatch):
    """A provider fault is a bad gateway, not an unhandled server error.

    The response is built inside the error boundary for this reason: a fault
    while shaping the reply used to escape as a 500 with no explanation.
    """
    class _Broken:
        def enrich(self, *a, **k):
            raise RuntimeError("provider is down")

    monkeypatch.setattr(enrichment, "LushaClient", lambda *a, **k: _Broken())

    res = client.post("/api/sales/xray/enrich", json={"people": PEOPLE})
    assert res.status_code == 502
    assert "provider is down" in res.json()["detail"]


# --- /reveal-phone ---------------------------------------------------------

def test_reveal_phone_returns_the_requested_person_and_number(client, fake_lusha):
    provider = fake_lusha({"error": None, "data": {"phoneNumbers": [{"number": "+15551234567"}]}})

    res = client.post("/api/sales/xray/reveal-phone", json={"person": PEOPLE[0]})
    assert res.status_code == 200
    assert res.json() == {"full_name": "Ada Lovelace", "phone": "+15551234567"}
    # Phone is deliberate and alone — revealing one must not also buy an email.
    assert provider.calls[0]["reveal_phones"] is True
    assert provider.calls[0]["reveal_emails"] is False


def test_reveal_phone_reports_no_number_without_failing(client, fake_lusha):
    fake_lusha({"error": None, "data": {"phoneNumbers": []}})

    res = client.post("/api/sales/xray/reveal-phone", json={"person": PEOPLE[0]})
    assert res.status_code == 200
    assert res.json()["phone"] is None
