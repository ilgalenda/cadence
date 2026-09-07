"""The acceptance bar for the one-off import of the hand-built tracker.

Three rules carry it:

  * **An ambiguous figure is not fitted.** A value that two different compositions
    hit exactly is imported *as the value*, with no composition — the same refusal
    the valuation module makes, for the same reason.
  * **The quoted field survives.** One row's notes contain commas inside quotes;
    a naive split shifts every column after it, which would silently mis-tier an
    account.
  * **The page's progress is replayed as dated events**, with the artefact named
    as the source, so the trail does not imply Cadence watched it happen.
"""
from __future__ import annotations

import json

import pytest

from agents.outbound import db, importer, store, valuation

#: Prices chosen so that uniqueness is actually testable. `quorum` and `single` are
#: deliberately a 2:1 pair, which is what makes £1,000 ambiguous; `odd` and `spare`
#: are coprime to everything else, so a total built from them has exactly one
#: reading. A fixture whose prices are all multiples of each other would make every
#: value ambiguous and prove nothing.
CATALOGUE = {
    "currency": "GBP",
    "shapes": {
        "quorum": {"composition": "3x", "price_gbp": 1000, "enterprise_grade": True},
        "single": {"composition": "1x", "price_gbp": 500, "enterprise_grade": True},
        "odd": {"composition": "1x odd", "price_gbp": 337, "enterprise_grade": True},
        "spare": {"composition": "1x spare", "price_gbp": 131, "enterprise_grade": False},
    },
    "support": {"standard_gbp_per_year": 200},
    "fleet_insight_annual_gbp": {"50": 900},
}

HEADER = (
    "account,segment,tier,campaign,trigger,geography,target_roles,confidence,"
    "t1_connect,t2_li_msg,t3_email,t4_value,t5_breakup,next_due,status,replied,"
    "procurement_route,value_est_gbp,notes"
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "outbound.db")
    db.init_db()
    monkeypatch.setattr(valuation, "load_catalogue", lambda path=None: CATALOGUE)


# ---------------------------------------------------------------------------
# Solving a composition
# ---------------------------------------------------------------------------

def test_a_value_with_one_composition_is_solved():
    assert importer.solve_composition(537, CATALOGUE) == {
        "deal_lines": [{"shape": "odd", "quantity": 1}],
        "attach_support": True,
        "fleet_insight_units": 0,
    }


def test_a_value_with_no_composition_is_not_solved():
    assert importer.solve_composition(1234, CATALOGUE) is None


def test_a_value_two_compositions_hit_is_refused_rather_than_picked():
    """1000 is one quorum and also two singles. Neither answer is imported."""
    assert importer.solve_composition(1000, CATALOGUE) is None


def test_a_subscription_is_part_of_the_search():
    assert importer.solve_composition(1237, CATALOGUE)["fleet_insight_units"] == 50


# ---------------------------------------------------------------------------
# Reading the CSV
# ---------------------------------------------------------------------------

def test_a_quoted_field_containing_commas_does_not_shift_the_columns(tmp_path):
    path = tmp_path / "tracker.csv"
    path.write_text(
        HEADER + "\n"
        'Parallel Wireless,ORAN,1,B-tdd,ORAN RAN,US,Head of Solutions,medium,'
        ',,,,,2026-08-26,not_started,no,,1200,'
        '"A prospect\'s stack runs their mesh, which is an integration angle, not a relationship"\n'
    )
    rows = importer.read_csv(path)
    assert rows[0]["tier"] == "1"
    assert rows[0]["value_est_gbp"] == "1200"
    assert rows[0]["notes"].startswith("A prospect's stack")


def test_an_unsolved_value_is_carried_and_flagged(tmp_path):
    path = tmp_path / "tracker.csv"
    path.write_text(
        HEADER + "\n"
        "Mystery,ORAN,1,B-tdd,,US,VP,medium,,,,,,2026-08-26,not_started,no,,1234,\n"
    )
    proposals, unsolved = importer.build_proposals(importer.read_csv(path), CATALOGUE)

    assert unsolved == [{"account": "Mystery", "value_est_gbp": 1234}]
    assert proposals[0]["value_est_gbp"] == 1234
    assert "no single composition" in proposals[0]["value_note"]
    assert "deal_lines" not in proposals[0]


def test_a_carried_figure_survives_landing_on_the_tracker(tmp_path):
    tracker = store.create_tracker("import", "sam")
    path = tmp_path / "tracker.csv"
    path.write_text(
        HEADER + "\n"
        "Mystery,ORAN,1,B-tdd,,US,VP,medium,,,,,,2026-08-26,not_started,no,,1234,\n"
    )
    proposals, _ = importer.build_proposals(importer.read_csv(path), CATALOGUE)
    store.add_rows(tracker["id"], proposals, actor="sam")

    row = store.get_rows(tracker["id"])[0]
    assert row["value_est_gbp"] == 1234
    assert store.counters(tracker["id"])["unpriced"] == 0


def test_repricing_leaves_a_carried_figure_alone(tmp_path):
    """It has no composition to recompute from; wiping it would lose the number."""
    tracker = store.create_tracker("import", "sam")
    path = tmp_path / "tracker.csv"
    path.write_text(
        HEADER + "\n"
        "Mystery,ORAN,1,B-tdd,,US,VP,medium,,,,,,2026-08-26,not_started,no,,1234,\n"
    )
    proposals, _ = importer.build_proposals(importer.read_csv(path), CATALOGUE)
    store.add_rows(tracker["id"], proposals, actor="sam")

    assert store.reprice(tracker["id"]) == {"repriced": 0}
    assert store.get_rows(tracker["id"])[0]["value_est_gbp"] == 1234


def test_a_trigger_from_the_csv_is_sourced_to_it(tmp_path):
    path = tmp_path / "tracker.csv"
    path.write_text(
        HEADER + "\n"
        "Meridian Towers,Neutral host,1,B-tdd,Multi-country scale,EU,CTO,high,,,,,,2026-08-20,"
        "not_started,no,,1200,\n"
    )
    proposals, _ = importer.build_proposals(importer.read_csv(path), CATALOGUE)
    assert proposals[0]["trigger_source"] == "outbound-tracker.csv"


# ---------------------------------------------------------------------------
# Replaying the page's progress
# ---------------------------------------------------------------------------

def test_the_pages_progress_lands_as_dated_events(tmp_path):
    tracker = store.create_tracker("import", "sam")
    store.add_rows(tracker["id"], [
        {"account": "Meridian Towers", "tier": 1, "confidence": "high",
         "deal_lines": [{"shape": "quorum"}]},
    ], actor="sam")

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps([{"a": "Meridian Towers", "t": [1, 1, 0, 0, 0], "s": "sequencing"}]))

    applied = importer.apply_state(tracker["id"], importer.read_state(state_path), actor="sam")
    assert (applied["touches"], applied["statuses"]) == (2, 1)

    row = store.get_rows(tracker["id"])[0]
    assert [t["fired"] for t in row["touches"]] == [True, True, False, False, False]
    assert {e["source"] for e in row["history"]} == {"artefact import"}


def test_a_status_the_page_holds_is_not_overwritten_by_the_first_touch(tmp_path):
    """`meeting` must survive; the auto-advance only fires from `not_started`."""
    tracker = store.create_tracker("import", "sam")
    store.add_rows(tracker["id"], [
        {"account": "IS-Wireless", "tier": 1, "confidence": "high",
         "deal_lines": [{"shape": "quorum"}]},
    ], actor="sam")

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps([{"a": "IS-Wireless", "t": [1, 0, 0, 0, 0], "s": "meeting"}]))

    importer.apply_state(tracker["id"], importer.read_state(state_path), actor="sam")
    assert store.get_rows(tracker["id"])[0]["status"] == "meeting"


def test_an_account_the_page_does_not_hold_is_reported_not_skipped_silently(tmp_path):
    tracker = store.create_tracker("import", "sam")
    store.add_rows(tracker["id"], [
        {"account": "Ghost", "tier": 1, "confidence": "high", "deal_lines": [{"shape": "quorum"}]},
    ], actor="sam")

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps([]))

    applied = importer.apply_state(tracker["id"], importer.read_state(state_path), actor="sam")
    assert applied["not_on_the_page"] == ["Ghost"]
