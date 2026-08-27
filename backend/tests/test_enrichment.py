"""Tests for the Lusha client and the Enrichment service.

The mocked tests lock the request contract (endpoint, api_key header, reveal
flags) and the response normalisation against an ASSUMED /v2/person envelope —
the live shape could not be fetched from Lusha's JS docs at build time. The live
smoke (opt-in via LUSHA_LIVE=1) confirms the real shape against a real key.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.services import enrichment
from agents.services.enrichment import Enrichment, EnrichedContact, _person_to_lusha_contact, _normalise_contact
from integrations import lusha
from integrations.lusha import LushaClient, LushaError, LushaAuthError, LushaRateLimitError


# --- fakes -----------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code=200, json_body=None, text="", bad_json=False):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._json


class _FakeHttp:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.resp


class _FakeClient:
    """Stand-in for LushaClient at the service layer; records reveal flags."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def enrich(self, contacts, *, reveal_emails=True, reveal_phones=False):
        self.calls.append({"contacts": contacts, "reveal_emails": reveal_emails, "reveal_phones": reveal_phones})
        return self.response


# The real single-person /v2/person envelope, confirmed live 2026-07-27.
def _canned(email=True, phone=False):
    data = {"fullName": "Jane Doe", "emailAddresses": [], "phoneNumbers": [], "phones": []}
    if email:
        data["emailAddresses"] = [{"email": "jane@acme.com", "emailType": "work", "emailConfidence": "A+"}]
    if phone:
        data["phoneNumbers"] = [{"number": "+15551234567", "phoneType": "mobile", "doNotCall": False}]
    return {"error": None, "isCreditCharged": email or phone, "data": data}


# --- LushaClient (transport) ----------------------------------------------

def test_client_posts_to_person_endpoint_with_api_key_and_flags():
    http = _FakeHttp(_FakeResp(json_body=_canned()))
    client = LushaClient(api_key="secret", http=http)
    client.enrich([{"contactId": "0", "fullName": "Jane"}], reveal_emails=True, reveal_phones=False)

    call = http.calls[0]
    assert call["url"] == "https://api.lusha.com/v2/person"
    assert call["headers"]["api_key"] == "secret"
    assert call["json"]["metadata"] == {"revealEmails": True, "revealPhones": False}
    assert call["json"]["contacts"][0]["fullName"] == "Jane"


def test_client_missing_key_raises(monkeypatch):
    monkeypatch.delenv("LUSHA_API_KEY", raising=False)
    with pytest.raises(LushaAuthError):
        LushaClient(api_key=None)


def test_client_empty_contacts_short_circuits():
    http = _FakeHttp(_FakeResp(json_body={"never": "called"}))
    client = LushaClient(api_key="k", http=http)
    assert client.enrich([]) == {"contacts": {}}
    assert http.calls == []


def test_client_too_many_contacts_raises():
    client = LushaClient(api_key="k", http=_FakeHttp(_FakeResp()))
    with pytest.raises(LushaError):
        client.enrich([{"contactId": str(i)} for i in range(lusha.MAX_BULK + 1)])


@pytest.mark.parametrize("status,exc", [(401, LushaAuthError), (429, LushaRateLimitError), (500, LushaError)])
def test_client_maps_error_statuses(status, exc):
    client = LushaClient(api_key="k", http=_FakeHttp(_FakeResp(status_code=status, text="boom")))
    with pytest.raises(exc):
        client.enrich([{"contactId": "0"}])


def test_client_non_json_raises():
    client = LushaClient(api_key="k", http=_FakeHttp(_FakeResp(bad_json=True)))
    with pytest.raises(LushaError):
        client.enrich([{"contactId": "0"}])


# --- Enrichment service ----------------------------------------------------

def test_enrich_reveals_email_only():
    client = _FakeClient(_canned(email=True, phone=False))
    result = Enrichment(client=client).enrich({"full_name": "Jane", "company": "Acme"})
    assert client.calls[0]["reveal_emails"] is True
    assert client.calls[0]["reveal_phones"] is False
    assert isinstance(result, EnrichedContact)
    assert result.primary_email == "jane@acme.com"
    assert result.phones == []


def test_reveal_phone_is_on_demand_only():
    client = _FakeClient(_canned(email=False, phone=True))
    result = Enrichment(client=client).reveal_phone({"full_name": "Jane"})
    assert client.calls[0]["reveal_phones"] is True
    assert client.calls[0]["reveal_emails"] is False
    assert result.primary_phone == "+15551234567"


def test_enrich_shortlist_is_one_bulk_email_call():
    # Bulk envelope is unconfirmed; the parser handles a `data` list (the natural
    # extension of the confirmed single shape) and a `contacts` map alike.
    response = {"error": None, "data": [
        {"fullName": "A", "emailAddresses": [{"email": "a@x.com"}]},
        {"fullName": "B", "emailAddresses": [{"email": "b@y.com"}]},
    ]}
    client = _FakeClient(response)
    out = Enrichment(client=client).enrich_shortlist([{"full_name": "A"}, {"full_name": "B"}])
    assert len(client.calls) == 1
    assert client.calls[0]["reveal_phones"] is False
    assert len(client.calls[0]["contacts"]) == 2
    assert {c.primary_email for c in out} == {"a@x.com", "b@y.com"}


def test_person_mapping_to_lusha_contact():
    contact = _person_to_lusha_contact(
        {"full_name": "Jane Doe", "linkedin_url": "https://li/in/jane", "company": "Acme"}, "0"
    )
    assert contact == {
        "contactId": "0",
        "fullName": "Jane Doe",
        "linkedinUrl": "https://li/in/jane",
        "companies": [{"isCurrent": True, "name": "Acme"}],
    }


def test_normalise_is_envelope_tolerant():
    # data-nested, dict items
    nested = _normalise_contact({"data": {
        "emailAddresses": [{"email": "a@x.com", "emailType": "work"}],
        "phoneNumbers": [{"number": "+1", "doNotCall": True}],
    }})
    assert nested.primary_email == "a@x.com"
    assert nested.phones[0]["do_not_call"] is True
    # top-level, string items under alternate keys
    flat = _normalise_contact({"emails": ["b@y.com"], "phones": ["+2"]})
    assert flat.primary_email == "b@y.com"
    assert flat.primary_phone == "+2"


# --- live smoke (opt-in) ---------------------------------------------------

@pytest.mark.skipif(not os.getenv("LUSHA_LIVE"), reason="set LUSHA_LIVE=1 to hit the real Lusha API")
def test_live_person_enrich_smoke(capsys):
    """Confirms the real /v2/person response shape against a real key.

    Run: LUSHA_LIVE=1 ./.venv/bin/python -m pytest tests/test_enrichment.py -k live -s
    """
    result = Enrichment().enrich({"full_name": "William Gates", "company": "Microsoft"})
    print("\nLUSHA RAW RESPONSE:\n", result.raw)
    print("PARSED emails:", result.emails, "| phones:", result.phones)
    assert isinstance(result.raw, dict)
