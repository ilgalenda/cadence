"""The acceptance bar for the events record.

Three rules carry the design, and each has a test that would fail if somebody
quietly relaxed it:

  * **One edition per show per year.** A second person registering interest in
    Northgate Expo 2026 joins the record; it does not fork it. This is what makes the table
    a calendar rather than a pile.
  * **Approval seeds the material.** A proposal orders nothing. The moment an
    edition, or a person's place on it, is approved, the deadlines exist.
  * **A decline is kept.** Why Acme said no to a show is worth as much next
    year as why it said yes, so nothing is hard-deleted.

Storage is isolated per test by pointing the module's `DB_PATH` at `tmp_path`
and re-running `init_db`, the seam `agents/mind/memory_db.py` already uses.
"""
from __future__ import annotations

from datetime import date

import pytest

from agents.events import db, requirements, store

#: A complete, valid proposal. Tests that check a rule override one key of it, so
#: each failure is attributable to the field the test is about.
IBC_2026 = {
    "name": "Northgate Expo 2026",
    "location": "Sødra Hallen",
    "country": "Netherlands",
    "starts_on": "2026-09-11",
    "ends_on": "2026-09-14",
    "needs_travel": True,
    "travel_legs": [{"mode": "flight", "from": "London", "to": "Amsterdam", "nights": 3}],
    "needs_material": True,
    "material_items": ["cards", "clothing"],
    "ticket_cost": 0,
    "invited": True,
    "rationale": "Lumen Broadcast and Halvard Media run ST 2110 trucks and are both reachable there.",
    "decide_by": "2026-08-20",
}


@pytest.fixture(autouse=True)
def events_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "events.db")
    db.init_db()
    return tmp_path


def _register(username="sam", **overrides):
    return store.register_interest(username, {**IBC_2026, **overrides})


class TestRegisteringInterest:
    def test_it_creates_a_proposed_edition_with_the_person_on_it(self):
        event = _register()
        assert event["status"] == "proposed"
        assert event["year"] == 2026
        assert event["location"] == "Sødra Hallen"
        assert len(event["registrations"]) == 1
        assert event["registrations"][0]["username"] == "sam"
        assert event["registrations"][0]["status"] == "proposed"

    def test_a_proposal_owes_nothing(self):
        assert _register()["checklist"] == []

    def test_a_second_person_joins_the_edition_rather_than_forking_it(self):
        _register("sam")
        event = _register("nils", name="Northgate Expo")  # the year in the title is noise
        assert len(event["registrations"]) == 2
        assert len(store.list_events()) == 1

    def test_the_same_person_cannot_register_twice(self):
        _register("sam")
        with pytest.raises(ValueError, match="already registered"):
            _register("sam")

    def test_next_year_is_a_separate_edition_of_the_same_show(self):
        _register("sam")
        _register("sam", starts_on="2027-09-10", ends_on="2027-09-13")
        assert len(store.list_events()) == 2
        assert {e["year"] for e in store.list_events()} == {2026, 2027}

    def test_a_bad_date_names_the_field_it_came_from(self):
        with pytest.raises(ValueError, match="Start date"):
            _register(starts_on="11 September")

    def test_the_event_cannot_end_before_it_starts(self):
        with pytest.raises(ValueError, match="cannot be before"):
            _register(ends_on="2026-09-01")

    def test_a_negative_ticket_price_is_refused(self):
        with pytest.raises(ValueError, match="negative"):
            _register(ticket_cost=-40)

    def test_a_blank_ticket_price_is_refused_rather_than_read_as_free(self):
        # "Unknown" and "free" look identical in an empty field and are different
        # facts to whoever is approving a cost.
        with pytest.raises(ValueError, match="Put 0 if the event is free"):
            _register(ticket_cost=None)


class TestTheShowBlock:
    """Every field required — but conditionally, which is the whole design.

    Demanding a stand cost from somebody attending a conference would block a
    valid registration, which is the opposite of making approval easier.
    """

    def test_location_and_country_are_required(self):
        with pytest.raises(ValueError, match="Say where it is held"):
            _register(location="")
        with pytest.raises(ValueError, match="Say which country"):
            _register(country="")

    def test_exhibiting_demands_a_stand_cost(self):
        with pytest.raises(ValueError, match="Stand cost is required"):
            _register(exhibiting=True, quote_contact_email="stands@acme.example")

    def test_exhibiting_demands_a_quote_contact(self):
        with pytest.raises(ValueError, match="quote contact email is required"):
            _register(exhibiting=True, exhibit_cost=12500)

    def test_a_quote_contact_that_is_not_an_address_is_refused(self):
        with pytest.raises(ValueError, match="does not look like an email address"):
            _register(exhibiting=True, exhibit_cost=12500, quote_contact_email="ask reception")

    def test_not_exhibiting_is_never_asked_for_a_stand_cost(self):
        event = _register(exhibiting=False)
        assert event["exhibit_cost"] is None
        assert event["exhibiting"] == 0

    def test_a_demo_demands_a_type(self):
        with pytest.raises(ValueError, match="what kind of demo"):
            _register(demo_required=True)

    def test_a_demo_type_is_kept(self):
        event = _register(demo_required=True, demo_type="vGMC + OTA Mini")
        assert event["demo_type"] == "vGMC + OTA Mini"

    def test_a_submission_deadline_is_demanded_only_when_there_is_one(self):
        assert _register()["submission_deadline"] is None
        with pytest.raises(ValueError, match="Submission deadline"):
            _register(has_submission_deadline=True)

    def test_a_submission_deadline_cannot_fall_after_the_event(self):
        with pytest.raises(ValueError, match="cannot be after the event starts"):
            _register(has_submission_deadline=True, submission_deadline="2026-09-30")


class TestTheCase:
    def test_the_case_for_going_is_required_and_must_say_something(self):
        with pytest.raises(ValueError, match="Say why we should go"):
            _register(rationale="")
        with pytest.raises(ValueError, match="Say why we should go"):
            _register(rationale="worth it")

    def test_the_case_is_kept_and_read_back(self):
        assert "Lumen Broadcast" in _register()["rationale"]

    def test_a_decide_by_date_is_required(self):
        with pytest.raises(ValueError, match="Decide-by date"):
            _register(decide_by=None)

    def test_deciding_after_the_show_has_started_is_not_deciding(self):
        with pytest.raises(ValueError, match="cannot be after the event starts"):
            _register(decide_by="2026-09-20")

    def test_the_table_counts_down_to_the_decision(self):
        _register()
        row = store.list_events(today=date(2026, 8, 10))[0]
        assert row["days_to_decide"] == 10


class TestJoiningRatherThanProposing:
    """The second person answers about themselves, not about the show again."""

    def test_joining_by_id_asks_nothing_about_the_show(self):
        first = _register("sam")
        joined = store.register_interest(
            "nils", {"event_id": first["id"], "intent": "attending", "ticket_cost": 0}
        )
        assert len(joined["registrations"]) == 2
        assert joined["rationale"] == first["rationale"]

    def test_joining_still_asks_about_the_person(self):
        first = _register("sam")
        with pytest.raises(ValueError, match="Ticket cost is required"):
            store.register_interest("nils", {"event_id": first["id"]})

    def test_joining_an_event_that_has_gone_is_refused(self):
        with pytest.raises(ValueError, match="no longer on the calendar"):
            store.register_interest("nils", {"event_id": "nope", "ticket_cost": 0})

    def test_proposing_something_already_on_the_calendar_joins_it_and_says_so(self):
        _register("sam")
        joined = _register("nils")
        assert joined["joined_existing"] is True
        assert len(store.list_events()) == 1

    def test_a_genuinely_new_proposal_does_not_claim_to_have_joined(self):
        assert _register("sam")["joined_existing"] is False


class TestApproval:
    def test_approving_an_edition_raises_its_checklist(self):
        event = _register()
        approved = store.decide_event(event["id"], status="approved", admin="sam")
        assert approved["status"] == "approved"
        assert approved["checklist_total"] > 0

    def test_the_stand_lines_follow_exhibiting_not_attending(self):
        plain = store.decide_event(_register("sam")["id"], status="approved", admin="sam")
        assert "Freight booked" not in {i["item"] for i in plain["checklist"]}

        show = _register("nils", name="Vantage Summit", starts_on="2026-10-06",
                         ends_on="2026-10-06", exhibiting=True, exhibit_cost=1,
                         quote_contact_email="a@b.c")
        exhibiting = store.decide_event(show["id"], status="approved", admin="sam")
        assert "Freight booked" in {i["item"] for i in exhibiting["checklist"]}

    def test_approving_a_persons_place_gives_them_cards_and_something_to_wear(self):
        event = _register()
        store.decide_event(event["id"], status="approved", admin="sam")
        reg_id = event["registrations"][0]["id"]
        after = store.decide_registration(reg_id, status="approved", admin="sam")
        theirs = {i["item"] for i in after["checklist"] if i["registration_id"] == reg_id}
        # This person needs travel, so their lines include the two the ops
        # manager books — raised per traveller, not per show.
        assert theirs == {"Business cards ordered", "Hoodie or quarter-zip ordered",
                          "Flights booked", "Accommodation booked"}

    def test_a_second_person_does_not_duplicate_the_shows_own_lines(self):
        _register("sam")
        event = _register("nils")
        store.decide_event(event["id"], status="approved", admin="sam")
        for registration in store.get_event(event["id"])["registrations"]:
            store.decide_registration(registration["id"], status="approved", admin="sam")

        lines = store.get_event(event["id"])["checklist"]
        show_lines = [i["item"] for i in lines if not i["registration_id"]]
        assert len(show_lines) == len(set(show_lines))
        # …while each person keeps their own copy of the personal ones.
        cards = [i for i in lines if i["item"] == "Business cards ordered"]
        assert len(cards) == 2

    def test_a_decline_is_recorded_rather_than_deleted(self):
        event = _register()
        declined = store.decide_event(
            event["id"], status="declined", admin="sam", note="Clashes with OCP"
        )
        assert declined["status"] == "declined"
        assert declined["decision_note"] == "Clashes with OCP"
        assert declined["decided_by"] == "sam"
        assert len(store.list_events()) == 1


class TestRequirements:
    def test_ticking_the_demo_box_raises_the_demo_lines_immediately(self):
        event = _register()
        store.decide_event(event["id"], status="approved", admin="sam")
        updated = store.update_event(
            event["id"], {"demo_required": True, "demo_type": "vGMC + OTA Mini"}
        )
        assert "Demo kit assembled" in {i["item"] for i in updated["checklist"]}

    def test_requirements_on_a_proposal_raise_nothing(self):
        event = _register()
        updated = store.update_event(event["id"], {"demo_required": True})
        assert updated["checklist"] == []

    def test_the_quote_contact_and_cost_are_kept(self):
        event = _register()
        updated = store.update_event(
            event["id"],
            {"exhibit_cost": 12500, "quote_contact_email": "stands@example.com"},
        )
        assert updated["exhibit_cost"] == 12500
        assert updated["quote_contact_email"] == "stands@example.com"

    def test_an_empty_update_is_refused_rather_than_silently_doing_nothing(self):
        event = _register()
        with pytest.raises(ValueError, match="Nothing to update"):
            store.update_event(event["id"], {})


class TestTheChecklist:
    def _approved(self):
        event = _register()
        store.decide_event(event["id"], status="approved", admin="sam")
        return store.decide_registration(
            event["registrations"][0]["id"], status="approved", admin="sam"
        )

    def test_approving_a_show_raises_the_playbook_against_it(self):
        after = self._approved()
        phases = {i["phase"] for i in after["checklist"]}
        assert "Decide" in phases and "Make" in phases and "After" in phases
        assert after["checklist_total"] == len(after["checklist"])

    def test_a_confirmed_person_gets_their_own_lines(self):
        after = self._approved()
        reg_id = after["registrations"][0]["id"]
        mine = {i["item"] for i in after["checklist"] if i["registration_id"] == reg_id}
        assert "Business cards ordered" in mine
        assert "Hoodie or quarter-zip ordered" in mine

    def test_the_two_hard_rules_land_on_the_right_dates(self):
        after = self._approved()
        by_item = {i["item"]: i["due_on"] for i in after["checklist"]}
        assert by_item["Business cards ordered"] == "2026-08-28"   # 14 days
        assert by_item["Pull-up banner ordered"] == "2026-08-21"   # 21 days

    def test_approving_twice_does_not_raise_the_list_twice(self):
        event = _register()
        store.decide_event(event["id"], status="approved", admin="sam")
        first = len(store.get_event(event["id"])["checklist"])
        store.decide_event(event["id"], status="approved", admin="sam")
        assert len(store.get_event(event["id"])["checklist"]) == first

    def test_a_proposal_owes_nothing_yet(self):
        assert _register()["checklist"] == []

    def test_cadence_reports_the_whole_list_outstanding_until_the_sheet_speaks(self):
        # Nothing has been reported done, which is true rather than optimistic.
        after = self._approved()
        assert after["outstanding"] == after["checklist_total"]
        assert after["ready"] is False

    def test_the_sheet_saying_everything_is_done_makes_it_ready(self):
        after = self._approved()
        store.record_progress({i["id"] for i in after["checklist"]})
        fresh = store.get_event(after["id"])
        assert fresh["outstanding"] == 0
        assert fresh["ready"] is True

    def test_a_partly_ticked_show_reports_what_is_left_and_when(self):
        after = self._approved()
        lines = sorted(after["checklist"], key=lambda i: i["due_on"])
        store.record_progress({lines[0]["id"]})

        fresh = store.get_event(after["id"])
        assert fresh["outstanding"] == len(lines) - 1
        assert fresh["next_due"] == lines[1]["due_on"]


class TestTheTable:
    def test_events_come_back_in_date_order_with_a_countdown(self):
        _register("sam", name="Timing Forum", starts_on="2026-11-02", ends_on="2026-11-05")
        _register("sam")  # IBC, September
        rows = store.list_events(today=date(2026, 9, 1))
        assert [r["name"] for r in rows] == ["Northgate Expo 2026", "Timing Forum"]
        assert rows[0]["days_until"] == 10

    def test_a_row_carries_what_the_show_still_owes(self):
        event = _register()
        store.decide_event(event["id"], status="approved", admin="sam")
        store.decide_registration(
            event["registrations"][0]["id"], status="approved", admin="sam"
        )
        row = store.list_events(today=date(2026, 9, 2))[0]
        assert row["outstanding"] == row["checklist_total"] > 0
        assert row["ready"] is False
        assert row["attendee_count"] == 1

    def test_years_are_listed_newest_first(self):
        _register("sam")
        _register("sam", starts_on="2027-09-10", ends_on="2027-09-13")
        assert store.years() == [2027, 2026]


class TestNextYear:
    def test_a_clone_carries_the_show_but_not_the_year(self):
        event = _register()
        store.update_event(
            event["id"],
            {
                "exhibiting": True,
                "exhibit_cost": 12500,
                "quote_contact_name": "RAI stand sales",
            },
        )
        store.decide_event(event["id"], status="approved", admin="sam")

        clone = store.clone_event(
            event["id"], {"starts_on": "2027-09-10", "ends_on": "2027-09-13"}, username="sam"
        )
        assert clone["year"] == 2027
        assert clone["exhibit_cost"] == 12500
        assert clone["quote_contact_name"] == "RAI stand sales"
        assert clone["status"] == "proposed"      # next year is argued for again
        assert clone["registrations"] == []
        assert clone["checklist"] == []

    def test_a_year_cannot_be_cloned_twice(self):
        event = _register()
        store.clone_event(
            event["id"], {"starts_on": "2027-09-10", "ends_on": "2027-09-13"}, username="sam"
        )
        with pytest.raises(ValueError, match="already has a 2027 edition"):
            store.clone_event(
                event["id"], {"starts_on": "2027-09-10", "ends_on": "2027-09-13"}, username="sam"
            )


class TestDeleting:
    """A delete removes the show and frees its slot.

    The second part is the one worth pinning: the uniqueness that stops two
    people forking Northgate Expo 2026 also, unqualified, stops anybody re-adding Northgate Expo 2026
    after it was deleted — which is what somebody does immediately after
    deleting a mistake.
    """

    def test_a_deleted_show_leaves_the_calendar(self):
        event = _register()
        store.delete_event(event["id"])
        assert store.list_events() == []

    def test_the_row_survives_so_nothing_is_actually_destroyed(self):
        event = _register()
        store.delete_event(event["id"])
        with db.connect() as conn:
            row = conn.execute(
                "SELECT deleted_at FROM events WHERE id = ?", (event["id"],)
            ).fetchone()
        assert row is not None and row["deleted_at"]

    def test_the_same_show_can_be_registered_again_afterwards(self):
        first = _register()
        store.delete_event(first["id"])

        again = _register()
        assert again["id"] != first["id"]
        assert len(store.list_events()) == 1

    def test_two_live_editions_of_one_show_are_still_impossible(self):
        # The partial index must not have relaxed the rule it exists for.
        _register("sam")
        joined = _register("nils")
        assert joined["joined_existing"] is True
        assert len(store.list_events()) == 1

    def test_deleting_something_already_gone_is_refused_readably(self):
        event = _register()
        store.delete_event(event["id"])
        with pytest.raises(ValueError, match="No such event"):
            store.delete_event(event["id"])

    def test_opening_a_deleted_show_is_refused(self):
        event = _register()
        store.delete_event(event["id"])
        with pytest.raises(ValueError, match="No such event"):
            store.get_event(event["id"])


class TestTheSchemaMigration:
    """A database made before the case and decide-by fields existed still opens.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so
    without `_add_missing_columns` a live database would keep the old shape and
    every write would fail on an unknown column. There is already such a database
    on this machine, which is why this is tested rather than assumed.
    """

    def test_an_old_database_gains_the_new_columns(self, tmp_path, monkeypatch):
        import sqlite3

        old = tmp_path / "old.db"
        conn = sqlite3.connect(old)
        # The schema as it shipped, minus the two columns added after it.
        conn.executescript(
            db._SCHEMA.replace("  rationale          TEXT NOT NULL DEFAULT '',\n", "")
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "DB_PATH", old)
        db.init_db()

        with db.connect() as c:
            columns = {r["name"] for r in c.execute("PRAGMA table_info(events)")}
        assert {"rationale", "decide_by"} <= columns

    def test_an_old_full_index_is_rebuilt_as_a_partial_one(self, tmp_path, monkeypatch):
        """The index shipped unqualified, and `CREATE ... IF NOT EXISTS` would
        have left it that way — so it is dropped by name and rebuilt."""
        import sqlite3

        old = tmp_path / "fullindex.db"
        conn = sqlite3.connect(old)
        conn.executescript(
            db._SCHEMA.replace(" WHERE deleted_at IS NULL;", ";")
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "DB_PATH", old)
        db.init_db()

        # The regression, end to end on a database that carried the old index.
        first = _register()
        store.delete_event(first["id"])
        assert _register()["id"] != first["id"]

    def test_and_the_migrated_database_can_then_be_written_to(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "again.db")
        db.init_db()
        db.init_db()  # idempotent — it runs on every start
        assert _register()["rationale"]


class TestWhatSomebodyAsksFor:
    """The two blocks the form added: material, and travel legs.

    The rule underneath all of them is that a tick and its detail travel
    together. A choice kept after the tick above it was cleared is a thing
    somebody changed their mind about, and ordering it anyway is the failure
    this block exists to prevent.
    """

    def _register(self, **overrides):
        return store.register_interest("theo", {**IBC_2026, **overrides})

    def test_the_choices_are_stored_against_the_person(self):
        event = self._register()
        registration = event["registrations"][0]
        assert requirements.load(registration["material_items"]) == ["cards", "clothing"]
        assert requirements.load(registration["travel_legs"])[0]["to"] == "Amsterdam"

    def test_unticking_material_clears_what_was_chosen_under_it(self):
        event = self._register(needs_material=False, material_items=["cards"],
                               material_note="A3 poster")
        registration = event["registrations"][0]
        assert registration["needs_material"] == 0
        assert registration["material_items"] == ""
        assert registration["material_note"] == ""

    def test_unticking_travel_clears_the_legs(self):
        event = self._register(needs_travel=False)
        assert event["registrations"][0]["travel_legs"] == ""

    def test_ticking_material_and_choosing_nothing_is_refused(self):
        with pytest.raises(ValueError, match="what material you need"):
            self._register(material_items=[])

    def test_choosing_something_else_without_saying_what_is_refused(self):
        with pytest.raises(ValueError, match="say what you need"):
            self._register(material_items=["other"], material_note="")

    def test_ticking_travel_and_adding_no_arrangement_is_refused(self):
        with pytest.raises(ValueError, match="at least one travel arrangement"):
            self._register(travel_legs=[])

    def test_a_show_can_be_registered_asking_for_nothing_at_all(self):
        # The commonest request there is: somebody local, with their own cards.
        event = self._register(needs_material=False, needs_travel=False)
        registration = event["registrations"][0]
        assert registration["needs_material"] == 0 and registration["needs_travel"] == 0

    def test_the_checklist_raises_only_what_was_asked_for(self):
        event = self._register(material_items=["cards"])
        store.decide_event(event["id"], status="approved", admin="sam")
        confirmed = store.decide_registration(
            event["registrations"][0]["id"], status="approved", admin="sam")
        lines = {i["item"] for i in confirmed["checklist"]}
        assert "Business cards ordered" in lines
        assert "Hoodie or quarter-zip ordered" not in lines
        assert "Flights booked" in lines
        assert "Train booked" not in lines


class TestRetiringAShow:
    """What a show that is off leaves behind, and what it stops claiming."""

    def _approved(self, name="Northgate Expo"):
        event = store.register_interest("theo", {**IBC_2026, "name": name})
        store.decide_event(event["id"], status="approved", admin="sam")
        store.decide_registration(
            event["registrations"][0]["id"], status="approved", admin="sam")
        return event["id"]

    def test_deleting_hands_back_the_show_it_hid(self):
        # The whole point of the return value: a deleted show is unreadable a
        # moment later, and the spreadsheet needs it to retire the right rows.
        event_id = self._approved()
        gone = store.delete_event(event_id)
        assert gone["id"] == event_id
        assert gone["deleted_at"]
        assert gone["registrations"] and gone["checklist"]

    def test_deleting_the_same_show_twice_is_still_refused(self):
        event_id = self._approved()
        store.delete_event(event_id)
        with pytest.raises(ValueError, match="No such event"):
            store.delete_event(event_id)

    def test_a_deleted_shows_lines_stop_being_counted(self):
        # Its rows are taken out of the sheet, so the sheet can never report
        # them done — counting them would leave a number nobody can bring down.
        live = self._approved("Northgate Expo")
        store.delete_event(self._approved("Vantage Summit"))
        assert store.record_progress(set()) == 1
        assert store.list_events()[0]["id"] == live

    def test_a_declined_shows_lines_stop_being_counted_too(self):
        self._approved("Northgate Expo")
        declined = self._approved("Vantage Summit")
        store.decide_event(declined, status="declined", admin="sam")
        assert store.record_progress(set()) == 1

    def test_a_retired_shows_cached_count_is_swept_away(self):
        event_id = self._approved()
        store.record_progress(set())
        store.delete_event(event_id)
        store.record_progress(set())
        with db.connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM sheet_state WHERE event_id = ?", (event_id,)
            ).fetchone()[0] == 0

    def test_a_declined_show_is_never_ready(self):
        # `ready` used to come from the tick count alone, so a show that was
        # said no to reported ready the moment its lines were all ticked.
        event_id = self._approved()
        items = store.get_event(event_id)["checklist"]
        store.record_progress({i["id"] for i in items})
        assert store.get_event(event_id)["ready"] is True

        store.decide_event(event_id, status="declined", admin="sam")
        assert store.get_event(event_id)["ready"] is False


class TestAdoptingLinesFromTheSpreadsheet:
    """A line typed into the sheet becomes a real line, or is left alone.

    The sheet writes as well as reads now, which is the change with the most
    ways to go wrong: a row attached to the wrong show puts work on the wrong
    calendar, and a row adopted twice counts the same job twice.
    """

    def _show(self, name="Northgate Expo 2026"):
        event = store.register_interest("theo", {**IBC_2026, "name": name})
        store.decide_event(event["id"], status="approved", admin="sam")
        return event["id"]

    def _line(self, **over):
        return {"row": 5, "show": "Northgate Expo 2026", "starts_on": IBC_2026["starts_on"],
                "phase": "Make", "item": "Roll banner", "owner": "Jo",
                "due_on": "2026-08-21", **over}

    def test_it_becomes_a_line_like_any_other(self):
        event_id = self._show()
        adopted, duplicates = store.adopt_lines([self._line()])
        assert list(adopted) == [5] and duplicates == []

        items = store.get_event(event_id)["checklist"]
        added = next(i for i in items if i["item"] == "Roll banner")
        assert added["id"] == adopted[5]
        assert added["owner"] == "Jo" and added["due_on"] == "2026-08-21"

    def test_it_is_counted_from_then_on(self):
        event_id = self._show()
        before = store.get_event(event_id)["checklist_total"]
        store.adopt_lines([self._line()])
        assert store.get_event(event_id)["checklist_total"] == before + 1

    def test_a_show_that_is_not_there_is_left_alone_rather_than_guessed_at(self):
        # An orphan is somebody's typo. Attaching it to the nearest show would
        # put work on the wrong calendar and nobody would know.
        self._show()
        assert store.adopt_lines([self._line(show="ITSF 2026")]) == ({}, [])

    def test_a_deleted_show_cannot_take_new_work(self):
        store.delete_event(self._show())
        assert store.adopt_lines([self._line()]) == ({}, [])

    def test_a_line_with_no_date_is_owed_when_the_show_opens(self):
        event_id = self._show()
        store.adopt_lines([self._line(due_on="")])
        added = next(i for i in store.get_event(event_id)["checklist"]
                     if i["item"] == "Roll banner")
        assert added["due_on"] == IBC_2026["starts_on"]

    def test_a_line_nobody_owns_falls_to_sam(self):
        event_id = self._show()
        store.adopt_lines([self._line(owner="")])
        added = next(i for i in store.get_event(event_id)["checklist"]
                     if i["item"] == "Roll banner")
        assert added["owner"] == "Sam"

    def test_it_belongs_to_the_show_not_to_a_person(self):
        # Nothing in the tab says whose it is, and guessing would put somebody's
        # name on work they never asked for.
        event_id = self._show()
        store.adopt_lines([self._line()])
        added = next(i for i in store.get_event(event_id)["checklist"]
                     if i["item"] == "Roll banner")
        assert added["registration_id"] is None

    def test_reseeding_the_playbook_leaves_it_where_it_is(self):
        # Approving a second person re-runs the seed; a hand-added line must
        # survive that untouched.
        event_id = self._show()
        store.adopt_lines([self._line()])
        store.register_interest("sam", {"event_id": event_id, "ticket_cost": 0})
        store.decide_event(event_id, status="approved", admin="sam")
        assert len([i for i in store.get_event(event_id)["checklist"]
                    if i["item"] == "Roll banner"]) == 1

    def test_adopting_the_same_row_twice_does_not_owe_the_job_twice(self):
        # The id written back into the sheet is what marks a row as adopted, and
        # that write is a network call that can fail. A second pass must not
        # raise the job again — and must not stamp the existing line's id into a
        # second row either, which would leave two rows claiming to be one line.
        event_id = self._show()
        store.adopt_lines([self._line()])
        adopted, duplicates = store.adopt_lines([self._line()])

        assert adopted == {} and duplicates == [5]
        assert len([i for i in store.get_event(event_id)["checklist"]
                    if i["item"] == "Roll banner"]) == 1

    def test_typing_a_line_the_show_already_has_removes_the_row(self):
        # It is on the list once, where it always was. A second row carrying the
        # same id would go stale and never update again.
        event_id = self._show()
        adopted, duplicates = store.adopt_lines([self._line(item="Lanyards ordered")])

        assert adopted == {} and duplicates == [5]
        assert len([i for i in store.get_event(event_id)["checklist"]
                    if i["item"] == "Lanyards ordered"]) == 1

    def test_two_years_of_one_show_are_told_apart_by_the_date(self):
        # The tab writes the name and the start date in separate columns and
        # does not repeat the year, so the name alone is not enough.
        this_year = self._show("Northgate Expo")
        next_year = store.register_interest("theo", {
            **IBC_2026, "name": "Northgate Expo",
            "starts_on": "2027-09-10", "ends_on": "2027-09-13"})["id"]
        store.decide_event(next_year, status="approved", admin="sam")

        store.adopt_lines([self._line(show="Northgate Expo", starts_on="2027-09-10")])
        assert any(i["item"] == "Roll banner"
                   for i in store.get_event(next_year)["checklist"])
        assert not any(i["item"] == "Roll banner"
                       for i in store.get_event(this_year)["checklist"])

    def test_a_name_that_could_mean_two_shows_is_left_alone(self):
        # Refused rather than resolved: a line on the wrong year is work on the
        # wrong calendar and nothing would say so. Left in the sheet, somebody
        # sees it and fixes it.
        self._show("Northgate Expo")
        second = store.register_interest("theo", {
            **IBC_2026, "name": "Northgate Expo",
            "starts_on": "2027-09-10", "ends_on": "2027-09-13"})["id"]
        store.decide_event(second, status="approved", admin="sam")

        assert store.adopt_lines([self._line(show="Northgate Expo", starts_on="")]) == ({}, [])

    def test_one_show_of_that_name_needs_no_date(self):
        event_id = self._show("Northgate Expo")
        store.adopt_lines([self._line(show="Northgate Expo", starts_on="")])
        assert any(i["item"] == "Roll banner"
                   for i in store.get_event(event_id)["checklist"])

    def test_nothing_to_adopt_touches_nothing(self):
        assert store.adopt_lines([]) == ({}, [])
