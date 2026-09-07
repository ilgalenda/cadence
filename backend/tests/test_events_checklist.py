"""The acceptance bar for the checklist.

The list is the playbook made tickable, so what is worth guarding is not the
wording of any line but the rules that decide **which lines a show gets** and
**when each is owed**. A checklist that raises a stand for a conference somebody
is merely attending is one people learn to skim, and a skimmed checklist is
worse than none.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from agents.events import checklist

STARTS = date(2026, 9, 11)

FLIGHT = json.dumps([{"mode": "flight", "from": "London", "to": "Amsterdam", "nights": 3}])
BOTH = json.dumps(["cards", "clothing"])
CARDS = json.dumps(["cards"])

BARE = {
    "starts_on": "2026-09-11",
    "exhibiting": 0,
    "demo_required": 0,
    "submission_deadline": None,
    "registrations": [
        # sam flies and stays over, and wants both the personal items.
        {"id": "r1", "username": "sam", "status": "approved", "needs_travel": 1,
         "travel_legs": FLIGHT, "needs_material": 1, "material_items": BOTH,
         "material_note": ""},
        # theo is local and wants cards only.
        {"id": "r2", "username": "theo", "status": "approved", "needs_travel": 0,
         "travel_legs": "", "needs_material": 1, "material_items": CARDS,
         "material_note": ""},
        # roy asked for everything and was declined, so he gets nothing.
        {"id": "r3", "username": "roy", "status": "declined", "needs_travel": 1,
         "travel_legs": FLIGHT, "needs_material": 1, "material_items": BOTH,
         "material_note": ""},
    ],
}

FULL = {**BARE, "exhibiting": 1, "demo_required": 1, "submission_deadline": "2026-08-29"}


def _items(event: dict) -> list[str]:
    return [item.item for item, _ in checklist.for_event(event)]


class TestTheListItself:
    def test_every_line_has_an_owner_and_a_phase(self):
        # A line nobody owns is a line nobody does.
        for item in checklist.CHECKLIST:
            assert item.owner, item.item
            assert item.phase, item.item

    def test_every_owner_is_somebody_named(self):
        allowed = {checklist.SAM, checklist.JO, checklist.OPERATIONS}
        assert {i.owner for i in checklist.CHECKLIST} <= allowed

    def test_no_line_is_written_twice(self):
        pairs = [(i.phase, i.item, i.applies) for i in checklist.CHECKLIST]
        assert len(set(pairs)) == len(pairs)

    def test_the_phases_run_in_time_order(self):
        # The sheet is read top to bottom, so the list is stored in the order
        # the work actually happens rather than sorted later.
        first_offset = {}
        for item in checklist.CHECKLIST:
            first_offset.setdefault(item.phase, item.offset)
        offsets = [first_offset[p] for p in checklist.PHASES]
        assert offsets == sorted(offsets)

    def test_the_two_hard_rules_are_where_the_masterplan_puts_them(self):
        by_item = {i.item: i for i in checklist.CHECKLIST}
        assert by_item["Business cards ordered"].offset == -14
        for made_for_us in ("Pull-up banner ordered", "Printed collateral ordered",
                            "Hoodie or quarter-zip ordered", "Demo kit assembled"):
            assert by_item[made_for_us].offset == -21, made_for_us


class TestWhichLinesAShowGets:
    def test_a_conference_gets_no_stand_lines(self):
        items = _items(BARE)
        for stand_only in ("Stand booked and contract signed", "Table covering ordered",
                           "Freight booked", "Stand power ordered"):
            assert stand_only not in items, stand_only

    def test_an_exhibition_gets_them(self):
        items = _items(FULL)
        for stand_only in ("Stand booked and contract signed", "Table covering ordered",
                           "Freight booked", "Stand power ordered"):
            assert stand_only in items, stand_only

    def test_no_demo_means_no_demo_lines(self):
        assert "Demo kit assembled" not in _items(BARE)
        assert "Demo kit assembled" in _items(FULL)

    def test_a_submission_line_appears_only_where_there_is_a_deadline(self):
        assert "Submission deadline diarised" not in _items(BARE)
        assert "Submission deadline diarised" in _items(FULL)

    def test_the_lines_everybody_gets_are_there_either_way(self):
        for always in ("Decision confirmed", "Target list built — who we want to meet, by name",
                       "Printed collateral ordered", "Recap written"):
            assert always in _items(BARE), always
            assert always in _items(FULL), always


class TestPerPersonLines:
    """The rule that changed: a line follows what somebody *asked for*.

    Cadence used to raise cards and clothing for every confirmed attendee, which
    ordered things nobody had said they needed. The form now asks, and these are
    the tests that stop the inference coming back.
    """

    def _people_for(self, event: dict, line: str) -> list[str]:
        return [r["username"] for item, r in checklist.for_event(event)
                if item.item == line and r]

    def test_a_line_is_raised_only_for_the_people_who_asked(self):
        # Both asked for cards; only sam asked for clothing.
        assert self._people_for(BARE, "Business cards ordered") == ["sam", "theo"]
        assert self._people_for(BARE, "Hoodie or quarter-zip ordered") == ["sam"]

    def test_unticking_material_silences_every_material_line(self):
        quiet = {**BARE, "registrations": [
            {**BARE["registrations"][0], "needs_material": 0},
        ]}
        assert self._people_for(quiet, "Business cards ordered") == []

    def test_a_declined_person_gets_nothing_however_much_they_asked_for(self):
        assert "roy" not in self._people_for(BARE, "Business cards ordered")
        assert "roy" not in self._people_for(BARE, "Flights booked")

    def test_each_travel_mode_raises_its_own_booking_line(self):
        # Operations books a train differently from a flight; one "travel" line
        # would hide which of them this is.
        mixed = {**BARE, "registrations": [{
            **BARE["registrations"][0],
            "travel_legs": json.dumps([
                {"mode": "train", "from": "London", "to": "Paris", "nights": 0},
                {"mode": "car", "from": "", "to": "", "nights": 0},
            ]),
        }]}
        assert self._people_for(mixed, "Train booked") == ["sam"]
        assert self._people_for(mixed, "Car hire booked") == ["sam"]
        assert self._people_for(mixed, "Flights booked") == []

    def test_accommodation_is_raised_once_however_many_legs_carry_nights(self):
        # Two legs of one trip describe the same nights away; a line each would
        # book the hotel twice.
        twice = {**BARE, "registrations": [{
            **BARE["registrations"][0],
            "travel_legs": json.dumps([
                {"mode": "flight", "from": "London", "to": "Amsterdam", "nights": 3},
                {"mode": "train", "from": "Amsterdam", "to": "Utrecht", "nights": 3},
            ]),
        }]}
        assert self._people_for(twice, checklist.requirements.ACCOMMODATION) == ["sam"]

    def test_a_day_trip_books_no_hotel(self):
        day = {**BARE, "registrations": [{
            **BARE["registrations"][0],
            "travel_legs": json.dumps([
                {"mode": "flight", "from": "London", "to": "Dublin", "nights": 0}]),
        }]}
        assert self._people_for(day, checklist.requirements.ACCOMMODATION) == []
        assert self._people_for(day, "Flights booked") == ["sam"]

    def test_free_text_material_is_raised_verbatim_and_given_to_mo(self):
        # Nothing else in the system knows what this is, so dropping it would
        # make the free-text box a lie.
        bespoke = {**BARE, "registrations": [{
            **BARE["registrations"][0],
            "material_items": json.dumps(["other"]),
            "material_note": "A3 poster of the sync topology",
        }]}
        raised = [item for item, r in checklist.for_event(bespoke) if r]
        assert [i.item for i in raised if i.item.startswith("Ordered:")] == [
            "Ordered: A3 poster of the sync topology"]
        assert all(i.owner == checklist.JO for i in raised
                   if i.item.startswith("Ordered:"))

    def test_choosing_other_without_saying_what_raises_nothing(self):
        empty = {**BARE, "registrations": [{
            **BARE["registrations"][0],
            "material_items": json.dumps(["other"]), "material_note": "",
        }]}
        assert not [i for i, r in checklist.for_event(empty)
                    if i.item.startswith("Ordered:")]

    def test_a_show_with_nobody_on_it_raises_no_personal_lines(self):
        alone = {**BARE, "registrations": []}
        assert "Business cards ordered" not in _items(alone)
        # …but the show's own lines still stand.
        assert "Decision confirmed" in _items(alone)


class TestTheTwoVocabulariesAgree:
    """Every material and every mode that promises a line has one.

    The form, the sheet and the checklist all read `requirements`, so a choice
    whose `raises` names a line nobody defined is a silent hole: the person asks,
    and nothing appears for anybody to do.
    """

    def test_every_material_that_raises_a_line_has_one_keyed_to_it(self):
        keyed = {i.requires: i for i in checklist.CHECKLIST
                 if i.applies == checklist.PER_PERSON}
        for material in checklist.requirements.MATERIAL:
            if not material.raises:
                continue
            assert material.key in keyed, material.key
            assert keyed[material.key].item == material.raises

    def test_every_travel_mode_has_its_booking_line(self):
        keyed = {i.requires: i.item for i in checklist.CHECKLIST
                 if i.applies == checklist.PER_TRAVELLER}
        for mode in checklist.requirements.MODES:
            assert keyed.get(mode.key) == mode.raises, mode.key


class TestWhenEachIsOwed:
    def test_dates_count_back_from_the_first_day_of_the_show(self):
        by_item = {i.item: i for i in checklist.CHECKLIST}
        assert checklist.due_on(STARTS, by_item["Business cards ordered"]) == date(2026, 8, 28)
        assert checklist.due_on(STARTS, by_item["Pull-up banner ordered"]) == date(2026, 8, 21)
        assert checklist.due_on(STARTS, by_item["Decision confirmed"]) == date(2026, 7, 31)

    def test_the_follow_up_lines_fall_after_the_show(self):
        by_item = {i.item: i for i in checklist.CHECKLIST}
        assert checklist.due_on(STARTS, by_item["Every conversation answered"]) == date(2026, 9, 13)
        assert checklist.due_on(STARTS, by_item["Recap written"]) == date(2026, 9, 25)

    def test_a_full_show_raises_more_lines_than_a_bare_one(self):
        assert len(checklist.for_event(FULL)) > len(checklist.for_event(BARE))
