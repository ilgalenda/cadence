"""Who can see which show — the acceptance bar for the events scope.

Until this existed, every signed-in person could read every event and its whole
record: stand costs, quote contacts, everybody's ticket price. The rule now is:

  * **an admin sees everything**;
  * **anybody else sees shows they are on** — confirmed, or their own proposal
    still waiting on a decision — and nothing that was declined.

The scope is a clause the query carries, not a filter applied afterwards, which
is the discipline `agents/sales/store/signals.py` already states. These tests
exercise it through the store; `test_events_routes.py` proves the routes pass it,
because a correct store says nothing about a route that forgets to use it.
"""
from __future__ import annotations

import pytest

from agents.events import db, store

SHOW = {
    "location": "Sødra Hallen",
    "country": "Netherlands",
    "ticket_cost": 0,
    "rationale": "Lumen Broadcast and Halvard Media run ST 2110 trucks and are reachable there.",
    "decide_by": "2026-08-20",
}


@pytest.fixture(autouse=True)
def events_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "events.db")
    db.init_db()


def _propose(username: str, name: str, starts: str = "2026-09-11") -> dict:
    return store.register_interest(username, {
        **SHOW, "name": name, "starts_on": starts, "ends_on": starts,
    })


class TestWhatAPersonSees:
    def test_their_own_proposal_still_waiting_on_a_decision(self):
        _propose("theo", "Northgate Expo")
        assert [e["name"] for e in store.list_events(username="theo")] == ["Northgate Expo"]

    def test_a_show_they_are_confirmed_for(self):
        event = _propose("theo", "Northgate Expo")
        store.decide_event(event["id"], status="approved", admin="sam")
        assert len(store.list_events(username="theo")) == 1

    def test_not_somebody_elses_show(self):
        _propose("sam", "Vantage Summit")
        assert store.list_events(username="theo") == []

    def test_not_a_show_that_was_declined(self):
        event = _propose("theo", "Northgate Expo")
        store.decide_event(event["id"], status="declined", admin="sam")
        assert store.list_events(username="theo") == []

    def test_not_a_show_they_were_declined_from(self):
        # The show goes ahead; this person does not. It is no longer theirs.
        event = _propose("sam", "Vantage Summit")
        store.register_interest("theo", {"event_id": event["id"], "ticket_cost": 0})
        reg = next(r for r in store.get_event(event["id"])["registrations"]
                   if r["username"] == "theo")
        store.decide_registration(reg["id"], status="declined", admin="sam")
        assert store.list_events(username="theo") == []

    def test_the_admin_sees_all_of_it(self):
        _propose("sam", "Vantage Summit")
        declined = _propose("theo", "Northgate Expo")
        store.decide_event(declined["id"], status="declined", admin="sam")
        assert len(store.list_events()) == 2


class TestOpeningOneByItsId:
    def test_a_show_they_are_on_opens(self):
        event = _propose("theo", "Northgate Expo")
        assert store.get_event(event["id"], username="theo")["name"] == "Northgate Expo"

    def test_a_show_they_are_not_on_reads_as_absent_not_forbidden(self):
        # Ids travel in emails and links. A route that answers differently for
        # "exists but not yours" is a way to enumerate what exists.
        event = _propose("sam", "Vantage Summit")
        with pytest.raises(ValueError, match="No such event"):
            store.get_event(event["id"], username="theo")

    def test_the_admin_opens_anything(self):
        event = _propose("theo", "Northgate Expo")
        assert store.get_event(event["id"])["name"] == "Northgate Expo"


# There is no `TestMovingMaterial` any more, and its absence is the point: with
# the checklist's state living in the spreadsheet, Cadence has no per-item write
# to scope. The reads below are the whole surface.


class TestTheProgression:
    def _approved(self, username: str = "theo"):
        event = _propose(username, "Northgate Expo")
        store.decide_event(event["id"], status="approved", admin="sam")
        return store.decide_registration(
            event["registrations"][0]["id"], status="approved", admin="sam"
        )

    def test_a_row_reports_everything_outstanding_until_the_sheet_speaks(self):
        after = self._approved()
        row = store.list_events()[0]
        assert row["checklist_total"] == after["checklist_total"] > 0
        assert row["outstanding"] == row["checklist_total"]
        assert row["ready"] is False

    def test_next_due_is_cadences_own_before_any_sync(self):
        # Cadence raised the lines and computed every date; only *which* remain
        # is the sheet's to say, so an unsynced show still shows what it owes.
        after = self._approved()
        assert store.list_events()[0]["next_due"] == min(
            i["due_on"] for i in after["checklist"]
        )

    def test_ticking_everything_in_the_sheet_makes_the_show_ready(self):
        after = self._approved()
        store.record_progress({i["id"] for i in after["checklist"]})
        row = store.list_events()[0]
        assert row["outstanding"] == 0 and row["ready"] is True

    def test_a_proposal_owes_nothing_and_is_not_ready_either(self):
        _propose("theo", "Northgate Expo")
        row = store.list_events()[0]
        assert row["checklist_total"] == 0
        assert row["ready"] is False
