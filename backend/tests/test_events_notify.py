"""The acceptance bar for the arrival email.

Two things are worth guarding, and neither is the SMTP conversation:

  * **The mail carries what the decision turns on.** The case somebody made and
    the date after which deciding stops being free. Without those it announces a
    registration rather than asking for an answer, which was its first version.
  * **"Nobody set this up" and "the server refused it" are different facts.**
    Both mean no mail arrived, and they send you to fix different things. The
    route reports which, and the page says so.

No test may reach a mail server: the transport is faked everywhere below.
"""
from __future__ import annotations

import pytest

from agents.events import notify
from agents.shared import notifications

EVENT = {
    "id": "abc123",
    "name": "Northgate Expo 2026",
    "location": "Sødra Hallen",
    "country": "Netherlands",
    "starts_on": "2026-09-11",
    "ends_on": "2026-09-14",
    "invited": 1,
    "decide_by": "2026-08-20",
    "days_to_decide": 4,
    "rationale": "Lumen Broadcast and Halvard Media run ST 2110 trucks and are both reachable there.",
    "registrations": [
        {
            "username": "theo",
            "intent": "attending",
            "needs_travel": 1,
            "travel_note": "flying from London",
            "ticket_cost": 0,
            "ticket_currency": "GBP",
        }
    ],
}

REGISTRATION = EVENT["registrations"][0]

SMTP_SETTINGS = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "cadence@example.com",
    "SMTP_PASSWORD": "not-a-real-password",
    "ADMIN_NOTIFY_EMAIL": "sam@example.com",
}


@pytest.fixture
def configured(monkeypatch):
    for key, value in SMTP_SETTINGS.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def no_base_url(monkeypatch):
    """Each test states its own, so none inherits the developer's environment."""
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)


class TestWhatTheMailSays:
    def test_it_carries_the_case_verbatim(self):
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "Lumen Broadcast and Halvard Media" in body
        assert "Why we should go" in body

    def test_it_carries_the_decide_by_date_and_the_countdown(self):
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "20 Aug 2026" in body
        assert "in 4 days" in body

    def test_dates_read_the_way_the_app_writes_them(self):
        # The mail and the page must not describe the same show differently.
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "11–14 Sep 2026" in body
        assert "2026-09-11" not in body

    def test_a_range_across_two_months_keeps_both(self):
        _, body = notify.compose(
            {**EVENT, "starts_on": "2026-10-30", "ends_on": "2026-11-02"}, REGISTRATION
        )
        assert "30 Oct 2026 – 2 Nov 2026" in body

    def test_an_overdue_decision_says_so(self):
        _, body = notify.compose({**EVENT, "days_to_decide": -3}, REGISTRATION)
        assert "OVERDUE" in body
        assert "3 days ago" in body

    def test_a_show_with_no_decide_by_date_simply_omits_the_line(self):
        _, body = notify.compose({**EVENT, "decide_by": None}, REGISTRATION)
        assert "Decide by" not in body

    def test_an_unstated_case_says_so_rather_than_leaving_a_gap(self):
        _, body = notify.compose({**EVENT, "rationale": "   "}, REGISTRATION)
        assert "Not stated." in body

    def test_the_subject_leads_with_the_show(self):
        # What a person scans an inbox for, and what survives truncation on a
        # phone. The sender already says this is Cadence.
        subject, _ = notify.compose(EVENT, REGISTRATION)
        assert subject == "Northgate Expo 2026 — theo wants to attend"
        assert not subject.startswith("[")

    def test_a_free_ticket_is_called_free(self):
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "free" in body

    def test_travel_carries_the_note_when_there_is_one(self):
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "flying from London" in body


class TestTheLink:
    def test_it_points_at_the_show(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://cadence.acme.example")
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "https://cadence.acme.example/work/events?event=abc123" in body

    def test_a_trailing_slash_does_not_double_up(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://cadence.acme.example/")
        assert notify.event_url("x") == "https://cadence.acme.example/work/events?event=x"

    def test_it_falls_back_to_the_origin_of_the_oauth_redirect(self, monkeypatch):
        # That URI must already match the deployment's public origin, or the
        # OAuth callback would not resolve — so it cannot be quietly wrong.
        monkeypatch.setenv(
            "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback"
        )
        assert notify.event_url("x") == "http://localhost:8000/work/events?event=x"

    def test_no_base_url_means_no_link_rather_than_a_broken_one(self):
        assert notify.event_url("x") == ""
        _, body = notify.compose(EVENT, REGISTRATION)
        assert "Approve or decline it" not in body

    def test_a_redirect_uri_that_is_not_a_url_yields_no_link(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_REDIRECT_URI", "not-a-url")
        assert notify.event_url("x") == ""


class TestTheDrawnHalf:
    """The HTML alternative. Same content, same order, and escaped."""

    def test_it_says_everything_the_text_says(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://cadence.acme.example")
        html = notify.compose_html(EVENT, REGISTRATION)
        for expected in ("Northgate Expo 2026", "theo", "Lumen Broadcast and Halvard Media",
                         "11–14 Sep 2026", "Sødra Hallen", "20 Aug 2026",
                         "https://cadence.acme.example/work/events?event=abc123"):
            assert expected in html, expected

    def test_the_case_is_escaped_because_somebody_typed_it(self):
        # The rationale is free text from a form. Unescaped it would be markup,
        # and an email client is a renderer like any other.
        html = notify.compose_html(
            {**EVENT, "rationale": '<script>alert("x")</script> & more'}, REGISTRATION
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp; more" in html

    def test_a_name_with_markup_in_it_cannot_break_the_layout(self):
        html = notify.compose_html({**EVENT, "name": 'IBC <b>2026</b>'}, REGISTRATION)
        assert "IBC <b>2026</b>" not in html
        assert "IBC &lt;b&gt;2026&lt;/b&gt;" in html

    def test_only_an_overdue_decision_takes_the_fault_colour(self):
        # `--signal-fault` is spent on a breach and nothing else, the same
        # restraint the page keeps. The "proposed" pill stays amber either way,
        # so the assertion is about the fault wash appearing at all.
        overdue = notify.compose_html({**EVENT, "days_to_decide": -2}, REGISTRATION)
        ahead = notify.compose_html(EVENT, REGISTRATION)
        assert "#FBEAE8" in overdue and "2 days ago" in overdue
        assert "#FBEAE8" not in ahead

    def test_no_base_url_means_no_button_rather_than_a_dead_one(self):
        html = notify.compose_html(EVENT, REGISTRATION)
        assert "Open in Cadence" not in html

    def test_it_is_a_complete_document(self):
        html = notify.compose_html(EVENT, REGISTRATION)
        assert html.startswith("<!doctype html>")
        assert html.rstrip().endswith("</html>")


class TestWhatHappened:
    def test_unconfigured_is_reported_as_itself(self, monkeypatch):
        for key in SMTP_SETTINGS:
            monkeypatch.delenv(key, raising=False)
        assert notify.registration_filed(EVENT, "theo") == notify.UNCONFIGURED

    def test_a_configured_send_that_works_reports_sent(self, configured, monkeypatch):
        monkeypatch.setattr(notify, "send_admin_email", lambda **kwargs: True)
        assert notify.registration_filed(EVENT, "theo") == notify.SENT

    def test_both_halves_are_handed_to_the_transport(self, configured, monkeypatch):
        # A client that will not render HTML must still get a whole message,
        # which is what the plain part is for.
        seen = {}
        monkeypatch.setattr(notify, "send_admin_email",
                            lambda **kwargs: seen.update(kwargs) or True)
        notify.registration_filed(EVENT, "theo")
        assert "Northgate Expo 2026" in seen["body"]
        assert seen["html"].startswith("<!doctype html>")

    def test_a_configured_send_that_fails_is_not_reported_as_unconfigured(
        self, configured, monkeypatch
    ):
        # The whole point of the distinction: this would otherwise send somebody
        # to add settings that are already there.
        monkeypatch.setattr(notify, "send_admin_email", lambda **kwargs: False)
        assert notify.registration_filed(EVENT, "theo") == notify.FAILED

    def test_a_registration_that_is_not_on_the_event_cannot_be_announced(self, configured):
        assert notify.registration_filed(EVENT, "nobody") == notify.FAILED


class TestIsConfigured:
    def test_every_setting_is_required(self, configured, monkeypatch):
        assert notifications.is_configured() is True
        for key in SMTP_SETTINGS:
            monkeypatch.delenv(key)
            assert notifications.is_configured() is False, key
            monkeypatch.setenv(key, SMTP_SETTINGS[key])
