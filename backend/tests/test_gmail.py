"""Acceptance bar for the Google grant and the Gmail client.

Two things matter more than the happy path here.

**The scope set is a promise to everyone who consents.** Adding to `SCOPES` makes
every user re-consent and widens what Cadence can touch, so it is asserted exactly —
a fourth scope appearing without a matching test change is a failure, not a diff
somebody might notice in review.

**The fence is asserted by name.** `gmail.py` deliberately exposes no read, list,
search or send. That is easy to erode one convenience at a time, so the absence is a
test: adding `search_messages` to the module breaks the suite and forces the person
adding it to say so out loud.
"""
from __future__ import annotations

import base64
import email
import email.policy

import pytest

from integrations import gmail
from integrations import google_oauth as grant


# ---------------------------------------------------------------------------
# The grant
# ---------------------------------------------------------------------------

def test_the_grant_asks_for_exactly_four_scopes():
    """Every entry here costs a re-consent from every user.

    `spreadsheets` joined the list on 2026-09-03 for the shared events working
    document — the tab Alex, Nils, Jo and operations read, none of whom have a
    Cadence account. Deliberately not a Drive scope: the Sheets API creates the
    file under the connecting account, and sharing it stays a person's decision.
    """
    assert grant.SCOPES == [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/spreadsheets",
    ]


def test_it_asks_for_no_drive_scope():
    """Reading somebody's whole Drive is not what a shared sheet needs."""
    joined = " ".join(grant.SCOPES)
    assert "auth/drive" not in joined


def test_it_asks_for_compose_and_not_modify():
    """`gmail.modify` would let the grant read the whole mailbox. Phase 4a chose not
    to, because the feature that would need it is not built."""
    joined = " ".join(grant.SCOPES)
    assert "gmail.compose" in joined
    assert "gmail.modify" not in joined
    assert "https://mail.google.com/" not in joined, "the full-access scope, never"


def test_the_authorize_url_carries_every_scope_and_keeps_prior_grants(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")

    url = grant.build_authorize_url("state-123")

    for scope in grant.SCOPES:
        assert scope.replace(":", "%3A").replace("/", "%2F") in url or scope in url
    # Without this, re-consenting for Gmail could drop Calendar.
    assert "include_granted_scopes=true" in url
    assert "access_type=offline" in url, "a refresh token is needed for background use"
    assert "state=state-123" in url


def test_the_token_file_path_did_not_move_when_the_grant_split_out():
    """Existing grants must keep working across the refactor.

    Asserted on the path's *shape*, not on identity with `sales_google_tokens()`:
    several test modules set `DATA_ROOT` process-wide at import time (see
    `test_owl_routes.py`), so a constant captured at import and a function called now
    legitimately disagree depending on collection order. The invariant that matters
    is the tail — the tokens still live where `agents/lead/data` always had them.
    """
    assert grant.TOKENS_FILE.name == "google_tokens.json"
    assert grant.TOKENS_FILE.parent.name == "data"
    assert grant.TOKENS_FILE.parent.parent.name == "lead"


@pytest.fixture
def tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(grant, "TOKENS_FILE", tmp_path / "google_tokens.json")
    return tmp_path


def test_a_grant_round_trips(tokens):
    grant.set_creds("sam", {"access_token": "a", "email": "i@t.app", "scopes": grant.SCOPES})
    assert (grant.get_creds("sam") or {})["email"] == "i@t.app"
    assert grant.granted_scopes("sam") == grant.SCOPES


def test_a_grant_made_before_scopes_were_recorded_reads_as_needing_reconnection(tokens):
    """It predates Gmail, so reporting it as missing everything is correct."""
    grant.set_creds("sam", {"access_token": "a", "email": "i@t.app"})

    assert grant.granted_scopes("sam") == []
    assert grant.missing_scopes("sam") == grant.SCOPES
    assert grant.can_draft_email("sam") is False


def test_a_calendar_only_grant_cannot_draft(tokens):
    grant.set_creds("sam", {"access_token": "a", "scopes": [grant.CALENDAR_SCOPE, grant.EMAIL_SCOPE]})

    assert grant.can_draft_email("sam") is False
    assert grant.missing_scopes("sam") == [grant.GMAIL_COMPOSE_SCOPE, grant.SHEETS_SCOPE]


def test_a_full_grant_can_draft(tokens):
    grant.set_creds("sam", {"access_token": "a", "scopes": grant.SCOPES})
    assert grant.can_draft_email("sam") is True
    assert grant.missing_scopes("sam") == []


def test_disconnecting_forgets_only_that_user(tokens):
    grant.set_creds("sam", {"access_token": "a"})
    grant.set_creds("martin", {"access_token": "b"})

    grant.clear_creds("sam")
    assert grant.get_creds("sam") is None
    assert grant.get_creds("martin") is not None


def test_a_corrupt_token_file_reads_as_nobody_connected(tokens):
    """Better than a 500 on every page that asks whether Google is connected."""
    grant.TOKENS_FILE.write_text("{ not json")
    assert grant.get_creds("sam") is None


# ---------------------------------------------------------------------------
# The fence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("forbidden", [
    "send", "send_draft", "send_message",
    "get_message", "read_message", "list_messages", "search_messages",
    "list_drafts", "get_draft", "list_threads", "get_thread",
])
def test_the_module_exposes_no_reader_and_no_sender(forbidden):
    """`gmail.compose` cannot read or send. If one of these appears, the scope has
    probably widened too — and that is a decision needing a re-consent, not a patch."""
    assert not hasattr(gmail, forbidden), (
        f"gmail.{forbidden} exists. Read the module docstring before adding it: the "
        "absence of a reader is the design, not an omission."
    )


def test_the_public_surface_is_the_three_draft_calls():
    public = {
        name for name in dir(gmail)
        if not name.startswith("_") and callable(getattr(gmail, name))
    }
    # `authorised_request` is imported, and GmailError is a class; neither is API.
    assert {"create_draft", "update_draft", "delete_draft"} <= public
    assert not any("send" in name or "search" in name for name in public)


# ---------------------------------------------------------------------------
# Encoding — the part that silently corrupts mail if it is wrong
# ---------------------------------------------------------------------------

def _decode(raw: str) -> email.message.Message:
    """The message as Gmail would receive it.

    `policy=default` so headers come back decoded: `EmailMessage` encodes a non-ASCII
    subject per RFC 2047 (`=?utf-8?q?...?=`), which is correct on the wire and
    unreadable in an assertion.
    """
    return email.message_from_bytes(
        base64.urlsafe_b64decode(raw), policy=email.policy.default,
    )


def test_a_draft_encodes_to_a_readable_message():
    raw = gmail._encode(
        to="lena@example.com",
        subject="Timestamping before the 2027 audit",
        body="Lena — thanks for the time today.",
    )
    message = _decode(raw)

    assert message["To"] == "lena@example.com"
    assert message["Subject"] == "Timestamping before the 2027 audit"
    assert "thanks for the time today" in message.get_payload(decode=True).decode("utf-8")


def test_a_unicode_subject_survives():
    """A µ in a subject line is ordinary in this product — 1.5 µs is the spec."""
    raw = gmail._encode(to="a@b.com", subject="Your 1.5 µs requirement", body="…")
    assert _decode(raw)["Subject"] == "Your 1.5 µs requirement"


def test_a_unicode_body_survives():
    raw = gmail._encode(to="a@b.com", subject="s", body="Holdover — 1.5 µs, ±10 ns.")
    body = _decode(raw).get_payload(decode=True).decode("utf-8")
    assert "1.5 µs, ±10 ns" in body


def test_cc_is_carried_when_given_and_absent_when_not():
    with_cc = _decode(gmail._encode(to="a@b.com", subject="s", body="b", cc=["c@d.com", "e@f.com"]))
    assert with_cc["Cc"] == "c@d.com, e@f.com"

    without = _decode(gmail._encode(to="a@b.com", subject="s", body="b"))
    assert without["Cc"] is None


def test_blank_cc_entries_are_dropped_rather_than_sent_as_empty():
    message = _decode(gmail._encode(to="a@b.com", subject="s", body="b", cc=["", "  ", "c@d.com"]))
    assert message["Cc"] == "c@d.com"


def test_the_encoding_is_url_safe_because_the_api_rejects_the_standard_alphabet():
    raw = gmail._encode(to="a@b.com", subject="s" * 200, body="b" * 4000)
    assert "+" not in raw and "/" not in raw


def test_a_long_body_is_not_truncated():
    body = "\n".join(f"line {n}" for n in range(500))
    decoded = _decode(gmail._encode(to="a@b.com", subject="s", body=body))
    assert "line 499" in decoded.get_payload(decode=True).decode("utf-8")


# ---------------------------------------------------------------------------
# The calls
# ---------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    """Capture what the client asks Google for, and serve a canned Draft."""
    seen: dict = {"answer": {"id": "d-1", "message": {"id": "m-1", "threadId": "t-1"}}}

    def fake(username, method, url, *, json_body=None, timeout=15):
        seen["username"] = username
        seen["method"] = method
        seen["url"] = url
        seen["body"] = json_body
        if isinstance(seen["answer"], Exception):
            raise seen["answer"]
        return seen["answer"]

    monkeypatch.setattr(gmail, "authorised_request", fake)
    return seen


def test_creating_a_draft_posts_to_the_drafts_endpoint(api):
    out = gmail.create_draft("sam", to="a@b.com", subject="s", body="b")

    assert (api["method"], api["url"]) == ("POST", gmail.DRAFTS_URL)
    assert api["username"] == "sam"
    assert out == {"draft_id": "d-1", "thread_id": "t-1"}


def test_the_message_id_is_deliberately_not_returned(api):
    """It changes on every update and again on send; storing it invites a stale id."""
    out = gmail.create_draft("sam", to="a@b.com", subject="s", body="b")
    assert "message_id" not in out


def test_a_draft_with_no_recipient_is_refused_before_a_call_is_made(api):
    with pytest.raises(gmail.GmailError, match="recipient"):
        gmail.create_draft("sam", to="   ", subject="s", body="b")
    assert "method" not in api, "no request should have been made"


def test_a_google_error_becomes_a_gmail_error(api):
    api["answer"] = RuntimeError("Google API error: 403 insufficient scope")
    with pytest.raises(gmail.GmailError, match="insufficient scope"):
        gmail.create_draft("sam", to="a@b.com", subject="s", body="b")


def test_a_response_with_no_draft_id_is_an_error_not_a_silent_success(api):
    api["answer"] = {"message": {"threadId": "t-1"}}
    with pytest.raises(gmail.GmailError, match="no draft id"):
        gmail.create_draft("sam", to="a@b.com", subject="s", body="b")


def test_updating_a_draft_replaces_it_in_place(api):
    out = gmail.update_draft("sam", "d-1", to="a@b.com", subject="s2", body="b2")

    assert api["method"] == "PUT"
    assert api["url"].endswith("/d-1")
    assert api["body"]["id"] == "d-1"
    assert out["draft_id"] == "d-1"


def test_deleting_a_draft_needs_an_id(api):
    with pytest.raises(gmail.GmailError, match="Which draft"):
        gmail.delete_draft("sam", "")

    gmail.delete_draft("sam", "d-1")
    assert api["method"] == "DELETE"
