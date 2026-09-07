"""The acceptance bar for the outbound tracker's record.

Four rules carry the design, and each has a test that would fail if somebody
quietly relaxed it:

  * **A touch is an event, not a flag.** Firing one appends a dated fact; clearing
    it appends another rather than erasing the first. Manual suppression depends on
    being able to tell "sent then retracted" from "never sent".
  * **An account is joined, not forked.** A second proposal naming an account
    already on the tracker leaves the state built against it alone.
  * **Every change is kept.** Status moves, edits and repricings all land in the
    trail with who did them, because a forecast whose figures move without a trace
    is unaccountable.
  * **Unpriced is reported, never folded away.** A total that silently omits rows
    reads as complete when it is not.

Storage is isolated per test by pointing the module's ``DB_PATH`` at ``tmp_path``
and re-running ``init_db``, the seam ``agents/events`` and ``agents/mind`` both use.
"""
from __future__ import annotations

import pytest

from agents.outbound import db, store, valuation

CATALOGUE = {
    "currency": "GBP",
    "shapes": {
        "primary_quorum": {"composition": "3x rubidium plus rack", "price_gbp": 1000, "enterprise_grade": True},
        "portable": {"composition": "1x mini per vehicle", "price_gbp": 100, "enterprise_grade": False},
    },
    "support": {"standard_gbp_per_year": 500},
    "fleet_insight_annual_gbp": {"100": 1600},
}

#: A complete, valid proposal. Tests that check a rule override one key of it, so
#: each failure is attributable to the field the test is about.
MERIDIAN = {
    "account": "Meridian Towers",
    "segment": "Neutral host",
    "tier": 1,
    "campaign": "B-tdd",
    "geography": "Spain/EU",
    "target_roles": "Network Architecture / Group CTO",
    "confidence": "high",
    "deal_lines": [{"shape": "primary_quorum", "quantity": 1}],
    "attach_support": True,
    "notes": "Multi-site framework, not a single sale.",
}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own database and its own fixture catalogue."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "outbound.db")
    db.init_db()
    monkeypatch.setattr(valuation, "load_catalogue", lambda path=None: CATALOGUE)


@pytest.fixture()
def tracker():
    return store.create_tracker(
        "Q4 outbound", "sam",
        goal_gbp=100000, target_touches=750, target_replies=35,
        target_calls=20, target_qualified=6,
    )


@pytest.fixture()
def row(tracker):
    store.add_rows(tracker["id"], [MERIDIAN], actor="sam")
    return store.get_rows(tracker["id"])[0]


# ---------------------------------------------------------------------------
# Trackers and rows
# ---------------------------------------------------------------------------

def test_a_tracker_needs_a_name():
    with pytest.raises(ValueError, match="needs a name"):
        store.create_tracker("   ", "sam")


def test_a_row_lands_priced(row):
    """The agent classifies the deal; the valuation module sets the figure."""
    assert row["value_est_gbp"] == 1500
    assert row["status"] == "not_started"
    assert [t["fired"] for t in row["touches"]] == [False] * 5


def test_an_unpriceable_row_still_lands(tracker):
    """A shape the catalogue does not know must not block the account."""
    store.add_rows(tracker["id"], [{**MERIDIAN, "deal_lines": [{"shape": "mystery"}]}], actor="sam")
    landed = store.get_rows(tracker["id"])[0]
    assert landed["value_est_gbp"] is None
    assert "not a shape" in landed["value_note"]


def test_an_account_already_on_the_tracker_is_joined_not_forked(tracker, row):
    store.fire_touch(row["id"], 1, actor="sam")
    result = store.add_rows(tracker["id"], [{**MERIDIAN, "notes": "different note"}], actor="sam")

    assert result["skipped"] == ["Meridian Towers"]
    rows = store.get_rows(tracker["id"])
    assert len(rows) == 1
    assert rows[0]["notes"] == MERIDIAN["notes"]
    assert rows[0]["touches"][0]["fired"] is True


@pytest.mark.parametrize(
    "bad,message",
    [
        ({"account": ""}, "needs an account name"),
        ({"tier": 4}, "tier must be"),
        ({"campaign": "D-something"}, "campaign must be"),
        ({"confidence": "certain"}, "confidence must be"),
    ],
)
def test_a_bad_field_is_refused_by_name(tracker, bad, message):
    with pytest.raises(ValueError, match=message):
        store.add_rows(tracker["id"], [{**MERIDIAN, **bad}], actor="sam")


def test_a_trigger_must_say_where_it_came_from(tracker):
    """An unsourced trigger is indistinguishable from an invented one."""
    with pytest.raises(ValueError, match="where it came from"):
        store.add_rows(
            tracker["id"], [{**MERIDIAN, "trigger_text": "TDD rollout announced"}], actor="sam"
        )


# ---------------------------------------------------------------------------
# A touch is an event
# ---------------------------------------------------------------------------

def test_firing_a_touch_dates_it_and_names_who(row):
    updated = store.fire_touch(row["id"], 3, actor="sam")
    touch = updated["touches"][2]
    assert touch["fired"] is True
    assert touch["actor"] == "sam"
    assert touch["at"]


def test_clearing_a_touch_keeps_the_fact_that_it_was_fired(row):
    store.fire_touch(row["id"], 1, actor="sam")
    cleared = store.fire_touch(row["id"], 1, actor="sam", fired=False)

    assert cleared["touches"][0]["fired"] is False
    touch_events = [e for e in cleared["history"] if e["kind"] == "touch"]
    assert [e["to_value"] for e in touch_events] == ["fired", "not_fired"]


def test_the_first_touch_moves_an_untouched_account_into_sequence(row):
    updated = store.fire_touch(row["id"], 1, actor="sam")
    assert updated["status"] == "sequencing"
    assert any(e["kind"] == "status" and e["to_value"] == "sequencing" for e in updated["history"])


def test_a_later_touch_does_not_re_move_a_status(row):
    store.fire_touch(row["id"], 1, actor="sam")
    store.set_status(row["id"], "meeting", actor="sam")
    updated = store.fire_touch(row["id"], 2, actor="sam")
    assert updated["status"] == "meeting"


def test_firing_a_touch_twice_is_refused(row):
    store.fire_touch(row["id"], 1, actor="sam")
    with pytest.raises(ValueError, match="already"):
        store.fire_touch(row["id"], 1, actor="sam")


@pytest.mark.parametrize("index", [0, 6, -1])
def test_a_touch_outside_the_five_is_refused(row, index):
    with pytest.raises(ValueError, match="touches"):
        store.fire_touch(row["id"], index, actor="sam")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_a_status_may_move_anywhere_and_the_move_is_kept(row):
    """A reply can arrive before any touch is logged; the record must allow it."""
    store.set_status(row["id"], "meeting", actor="sam")
    updated = store.set_status(row["id"], "sequencing", actor="sam", source="mis-click")

    assert updated["status"] == "sequencing"
    moves = [(e["from_value"], e["to_value"]) for e in updated["history"] if e["kind"] == "status"]
    assert moves == [("not_started", "meeting"), ("meeting", "sequencing")]


def test_an_unknown_status_is_refused(row):
    with pytest.raises(ValueError, match="is not a status"):
        store.set_status(row["id"], "warm", actor="sam")


def test_setting_the_status_it_already_has_is_refused(row):
    with pytest.raises(ValueError, match="already"):
        store.set_status(row["id"], "not_started", actor="sam")


# ---------------------------------------------------------------------------
# Edits and repricing
# ---------------------------------------------------------------------------

def test_only_the_fields_a_person_owns_are_editable(row):
    with pytest.raises(ValueError, match="cannot be edited here"):
        store.update_row(row["id"], {"value_est_gbp": 999}, actor="sam")


def test_an_edit_is_recorded(row):
    updated = store.update_row(row["id"], {"procurement_route": "via reseller"}, actor="sam")
    assert updated["procurement_route"] == "via reseller"
    edits = [e for e in updated["history"] if e["kind"] == "edit"]
    assert edits[0]["to_value"] == "procurement_route=via reseller"


def test_an_edit_to_the_same_value_records_nothing(row):
    store.update_row(row["id"], {"notes": MERIDIAN["notes"]}, actor="sam")
    assert store.get_row(row["id"])["history"] == []


def test_repricing_records_every_figure_that_moved(tracker, row, monkeypatch):
    dearer = {**CATALOGUE, "shapes": {**CATALOGUE["shapes"],
              "primary_quorum": {"composition": "3x", "price_gbp": 2000, "enterprise_grade": True}}}
    monkeypatch.setattr(valuation, "load_catalogue", lambda path=None: dearer)

    assert store.reprice(tracker["id"]) == {"repriced": 1}
    updated = store.get_row(row["id"])
    assert updated["value_est_gbp"] == 2500
    value_events = [e for e in updated["history"] if e["kind"] == "value"]
    assert (value_events[0]["from_value"], value_events[0]["to_value"]) == ("1500", "2500")


def test_repricing_with_no_change_records_nothing(tracker, row):
    assert store.reprice(tracker["id"]) == {"repriced": 0}
    assert store.get_row(row["id"])["history"] == []


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

def test_counters_count_what_the_header_reports(tracker):
    store.add_rows(tracker["id"], [
        MERIDIAN,
        {**MERIDIAN, "account": "Dense Air"},
        {**MERIDIAN, "account": "Corvus Radio"},
        {**MERIDIAN, "account": "Mystery", "deal_lines": [{"shape": "unknown"}]},
    ], actor="sam")
    rows = {r["account"]: r for r in store.get_rows(tracker["id"])}

    store.fire_touch(rows["Meridian Towers"]["id"], 1, actor="sam")
    store.fire_touch(rows["Meridian Towers"]["id"], 2, actor="sam")
    store.fire_touch(rows["Dense Air"]["id"], 1, actor="sam")
    store.set_status(rows["Dense Air"]["id"], "qualified", actor="sam")
    store.set_status(rows["Corvus Radio"]["id"], "replied", actor="sam")

    counted = store.counters(tracker["id"])
    assert counted["targets"] == 4
    assert counted["touches"] == 3
    assert counted["in_sequence"] == 2
    assert counted["replies"] == 2
    assert counted["calls"] == 1
    assert counted["qualified"] == 1
    assert counted["qualified_value_gbp"] == 1500
    assert counted["target_touches"] == 750
    assert counted["goal_gbp"] == 100000


def test_a_carried_figure_is_counted_as_uncomposed_not_unpriced(tracker):
    """It has a number, so it counts in the total; it has no composition, so it
    cannot be repriced. Those are different facts and are reported separately."""
    store.add_rows(tracker["id"], [
        MERIDIAN,
        {**MERIDIAN, "account": "Corvus Radio", "deal_lines": [], "attach_support": False,
         "value_est_gbp": 20000},
    ], actor="sam")
    counted = store.counters(tracker["id"])
    assert counted["unpriced"] == 0
    assert counted["uncomposed"] == 1
    assert counted["total_value_gbp"] == 21500


def test_unpriced_rows_are_reported_beside_the_total(tracker):
    store.add_rows(tracker["id"], [
        MERIDIAN,
        {**MERIDIAN, "account": "Mystery", "deal_lines": [{"shape": "unknown"}]},
    ], actor="sam")
    counted = store.counters(tracker["id"])
    assert counted["total_value_gbp"] == 1500
    assert counted["unpriced"] == 1


def test_a_cleared_touch_stops_being_counted(tracker, row):
    store.fire_touch(row["id"], 1, actor="sam")
    assert store.counters(tracker["id"])["touches"] == 1
    store.fire_touch(row["id"], 1, actor="sam", fired=False)
    assert store.counters(tracker["id"])["touches"] == 0


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def test_an_unreachable_tracker_says_so_rather_than_failing_oddly():
    with pytest.raises(ValueError, match="No such tracker"):
        store.counters("nonexistent")


def test_an_unreachable_row_says_so():
    with pytest.raises(ValueError, match="No such account"):
        store.set_status("nonexistent", "replied", actor="sam")


def test_the_artifact_url_is_recorded_on_the_tracker(tracker):
    updated = store.set_artifact_url(tracker["id"], "https://claude.ai/code/artifact/abc")
    assert updated["artifact_url"] == "https://claude.ai/code/artifact/abc"
    assert store.get_tracker(tracker["id"])["artifact_url"].endswith("abc")


def test_trackers_are_listed_per_person(tracker):
    store.create_tracker("Someone else's", "nils")
    assert [t["name"] for t in store.list_trackers("sam")] == ["Q4 outbound"]
    assert len(store.list_trackers()) == 2


# ---------------------------------------------------------------------------
# Deleting a campaign
# ---------------------------------------------------------------------------

def test_deleting_a_campaign_takes_its_accounts_and_their_trail(tracker):
    """The one destructive operation here, so what it destroys is asserted."""
    store.add_rows(tracker["id"], [MERIDIAN, {**MERIDIAN, "account": "Corvus Radio"}], actor="sam")
    row = store.get_rows(tracker["id"])[0]
    store.fire_touch(row["id"], 1, actor="sam")

    removed = store.delete_tracker(tracker["id"])

    assert removed["name"] == "Q4 outbound"
    assert removed["accounts"] == 2
    assert removed["touches"] == 1
    assert removed["events"] >= 2  # the touch, and the status it advanced
    assert store.get_tracker(tracker["id"]) is None
    assert store.get_row(row["id"]) is None


def test_deleting_reports_how_much_work_went_with_it(tracker):
    """The trail is the suppression record, so its size is worth saying."""
    store.add_rows(tracker["id"], [MERIDIAN], actor="sam")
    row = store.get_rows(tracker["id"])[0]
    for index in (1, 2, 3):
        store.fire_touch(row["id"], index, actor="sam")

    removed = store.delete_tracker(tracker["id"])
    assert removed["touches"] == 3


def test_deleting_an_untouched_campaign_says_so(tracker):
    store.add_rows(tracker["id"], [MERIDIAN], actor="sam")
    removed = store.delete_tracker(tracker["id"])
    assert (removed["accounts"], removed["touches"], removed["events"]) == (1, 0, 0)


def test_deleting_leaves_every_other_campaign_alone(tracker):
    other = store.create_tracker("Nordic ORAN", "sam")
    store.add_rows(other["id"], [MERIDIAN], actor="sam")
    store.add_rows(tracker["id"], [{**MERIDIAN, "account": "Corvus Radio"}], actor="sam")

    store.delete_tracker(tracker["id"])

    assert [t["name"] for t in store.list_trackers()] == ["Nordic ORAN"]
    assert [r["account"] for r in store.get_rows(other["id"])] == ["Meridian Towers"]


def test_deleting_a_campaign_that_is_not_there_is_refused_by_name():
    with pytest.raises(ValueError, match="No such tracker"):
        store.delete_tracker("nonexistent")
