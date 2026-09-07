"""The acceptance bar for what a person asks for.

This module is the only place the material list and the travel modes are written
down, so what is worth guarding is that **a person's answer survives intact** —
through validation, into storage, and back out as something Jo or Operations can
act on without asking them what they meant.

The nastier cases are the ones a form produces by accident: a leg added and left
blank, a nights box somebody typed a word into, the same item chosen twice.
"""
from __future__ import annotations

import pytest

from agents.events import requirements as req


class TestMaterial:
    def test_the_choices_come_back_in_the_lists_own_order(self):
        # Not the order they were clicked: two people who asked for the same
        # things should produce the same row.
        assert req.clean_material(["clothing", "cards"]) == ["cards", "clothing"]

    def test_the_same_choice_twice_is_one_choice(self):
        assert req.clean_material(["cards", "cards"]) == ["cards"]

    def test_something_that_is_not_a_choice_is_dropped(self):
        assert req.clean_material(["cards", "helicopter"]) == ["cards"]

    def test_anything_that_is_not_a_list_reads_as_nothing_chosen(self):
        assert req.clean_material("cards") == []
        assert req.clean_material(None) == []

    def test_it_reads_back_as_labels_not_keys(self):
        assert req.describe_material(["cards"]) == "Business cards"

    def test_free_text_is_carried_verbatim(self):
        described = req.describe_material(["cards", "other"], "A3 poster")
        assert described == "Business cards\nA3 poster"

    def test_other_with_nothing_typed_says_so_rather_than_going_quiet(self):
        # A silent drop would leave Jo believing this person asked for nothing.
        assert "not specified" in req.describe_material(["other"], "")

    def test_a_retired_key_still_reads_as_what_was_asked_for(self):
        assert req.material_label("gone") == "gone"


class TestTravel:
    FLIGHT = {"mode": "flight", "from": "London", "to": "Amsterdam", "nights": 3}

    def test_a_leg_reads_as_a_line_operations_can_book_from(self):
        assert req.describe_leg(self.FLIGHT) == "Flight, London → Amsterdam, 3 nights"

    def test_one_night_is_not_pluralised(self):
        assert req.describe_leg({**self.FLIGHT, "nights": 1}).endswith("1 night")

    def test_a_day_trip_says_nothing_about_nights(self):
        assert req.describe_leg({**self.FLIGHT, "nights": 0}) == \
            "Flight, London → Amsterdam"

    def test_a_car_hire_needs_no_route(self):
        assert req.describe_leg(
            {"mode": "car", "from": "", "to": "", "nights": 0}) == "Car hire"

    def test_a_blank_leg_is_dropped_rather_than_refused(self):
        # The form adds an empty leg the moment somebody presses Add. Refusing
        # to submit because of it punishes them for the interface.
        assert req.clean_legs([{"mode": "", "from": "", "to": ""}, self.FLIGHT]) == \
            [self.FLIGHT]

    def test_nights_that_are_not_a_number_are_refused_readably(self):
        with pytest.raises(ValueError, match="whole number"):
            req.clean_legs([{**self.FLIGHT, "nights": "a fortnight"}])

    def test_an_absurd_number_of_nights_is_refused(self):
        with pytest.raises(ValueError, match="more than"):
            req.clean_legs([{**self.FLIGHT, "nights": 400}])

    def test_a_negative_number_of_nights_reads_as_none(self):
        assert req.clean_legs([{**self.FLIGHT, "nights": -2}])[0]["nights"] == 0

    def test_more_legs_than_anybody_needs_are_cut_off(self):
        assert len(req.clean_legs([self.FLIGHT] * 40)) == req.MAX_LEGS

    def test_nights_is_the_longest_leg_not_the_sum(self):
        # Two legs of one trip describe the same nights away from home.
        assert req.nights([self.FLIGHT, {**self.FLIGHT, "nights": 3}]) == 3

    def test_no_legs_is_no_nights(self):
        assert req.nights([]) == 0


class TestStoringIt:
    def test_a_list_survives_the_round_trip(self):
        assert req.load(req.dump(["cards"])) == ["cards"]

    def test_nothing_stores_as_nothing_rather_than_an_empty_list(self):
        # An empty cell reads as empty in the database browser too.
        assert req.dump([]) == ""

    def test_a_column_written_before_this_existed_does_not_take_the_page_down(self):
        assert req.load(None) == []
        assert req.load("not json") == []
        assert req.load('{"cards": true}') == []
