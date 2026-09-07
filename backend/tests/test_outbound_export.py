"""The acceptance bar for the published snapshot.

Three rules carry it, and each is the reason the export exists rather than a
preference about how it looks:

  * **It cannot be ticked.** No Save button, no `window.claude`, no touch control.
    The page it replaces saved new versions of itself, and that is how the working
    surface and the vault's copy of the list came to disagree on fifteen accounts.
  * **It says it is a snapshot, and when.** A page that does not date itself gets
    worked in.
  * **The columns are declared once.** The header row is built from the same list
    that fills the cells, so a header cannot drift from its column — and every
    value is escaped, because these are account names and notes somebody typed.

The price catalogue must never reach a published page; a row's own agreed figure
may, because that is what the tracker reports.
"""
from __future__ import annotations

import json
import re

import pytest

from agents.outbound import db, export, store, valuation

CATALOGUE = {
    "currency": "GBP",
    "shapes": {"primary_quorum": {"composition": "3x rubidium", "price_gbp": 1000, "enterprise_grade": True}},
    "support": {"standard_gbp_per_year": 500},
}

MERIDIAN = {
    "account": "Meridian Towers",
    "segment": "Neutral host",
    "tier": 1,
    "campaign": "B-tdd",
    "geography": "Spain/EU",
    "target_roles": "Group CTO",
    "confidence": "high",
    "deal_lines": [{"shape": "primary_quorum"}],
    "attach_support": True,
    "trigger_text": "Multi-country neutral host scale",
    "trigger_source": "outbound-tracker.csv",
    "next_due": "2026-09-20",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "outbound.db")
    db.init_db()
    monkeypatch.setattr(valuation, "load_catalogue", lambda path=None: CATALOGUE)


@pytest.fixture()
def page():
    tracker = store.create_tracker(
        "Q4 outbound", "sam",
        goal_gbp=100000, target_touches=750, target_replies=35,
        target_calls=20, target_qualified=6,
    )
    store.add_rows(tracker["id"], [
        MERIDIAN,
        {**MERIDIAN, "account": "Corvus Radio", "deal_lines": [], "attach_support": False,
         "value_est_gbp": 20000, "trigger_text": "", "trigger_source": ""},
    ], actor="sam")
    rows = {r["account"]: r for r in store.get_rows(tracker["id"])}
    store.fire_touch(rows["Meridian Towers"]["id"], 1, actor="sam")
    store.set_status(rows["Corvus Radio"]["id"], "qualified", actor="sam")
    return tracker["id"], export.render(tracker["id"])


# ---------------------------------------------------------------------------
# It cannot be ticked
# ---------------------------------------------------------------------------

def test_the_snapshot_has_no_way_to_record_anything(page):
    _, html = page
    for forbidden in ("window.claude", "api.publish", "<button", "<input", "Save"):
        assert forbidden not in html, forbidden


def test_it_says_it_is_a_snapshot_and_when(page):
    _, html = page
    assert "Snapshot." in html
    assert "Read-only" in html
    assert re.search(r"Taken \d{2} \w+ \d{4}, \d{2}:\d{2} UTC", html)


def test_the_stamp_can_be_pinned_for_a_diff(page):
    tracker_id, _ = page
    html = export.render(tracker_id, taken_at="01 January 2026, 00:00 UTC")
    assert "Taken 01 January 2026, 00:00 UTC" in html


# ---------------------------------------------------------------------------
# The columns
# ---------------------------------------------------------------------------

def test_the_header_row_is_built_from_the_column_list(page):
    _, html = page
    head = re.search(r"<thead><tr>(.*?)</tr></thead>", html, re.S).group(1)
    assert head.count("<th>") == len(export.COLUMNS)
    for header, _, _ in export.COLUMNS:
        assert f"<th>{header}</th>" in head


def test_every_row_fills_every_column(page):
    _, html = page
    body = re.findall(r"<tr>(<td.*?)</tr>", html, re.S)
    assert body, "no data rows rendered"
    for cells in body:
        assert cells.count("<td") == len(export.COLUMNS)


def test_target_roles_are_not_published(page):
    """They are on the record in Cadence; a ninth column pushed the figure off."""
    _, html = page
    assert "Group CTO" not in html
    assert not any(header == "Roles" for header, _, _ in export.COLUMNS)


def test_an_absent_value_writes_a_dash_not_a_blank(page):
    _, html = page
    # Corvus Radio has no trigger. A blank cell reads as "not filled in yet".
    assert "<td class=\"cell--trigger\">—</td>" in html


def test_an_account_name_is_escaped(tmp_path):
    """These are names and notes somebody typed into a research pass."""
    tracker = store.create_tracker("Q4", "sam")
    store.add_rows(tracker["id"], [
        {**MERIDIAN, "account": '<script>alert(1)</script>', "notes": '"quoted" & <b>'},
    ], actor="sam")
    html = export.render(tracker["id"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# What it reports
# ---------------------------------------------------------------------------

def test_the_counters_are_the_records_own(page):
    tracker_id, html = page
    counters = store.counters(tracker_id)
    assert f'>{counters["touches"]}<' in html
    assert "of 750" in html
    assert "of £100,000" in html


def test_a_carried_figure_is_named_as_unrepriceable(page):
    _, html = page
    assert "cannot be repriced" in html


def test_unpriced_reads_as_a_word_not_a_zero(tmp_path):
    tracker = store.create_tracker("Q4", "sam")
    store.add_rows(tracker["id"], [{**MERIDIAN, "deal_lines": [{"shape": "mystery"}]}], actor="sam")
    html = export.render(tracker["id"])
    # The row's own cell, not the page: the qualified-value tile legitimately
    # reads £0 when nothing has qualified yet.
    assert '<td class="cell--num">unpriced</td>' in html


def test_the_page_carries_its_own_numbers_as_data(page):
    """A snapshot whose figures exist only as rendered text cannot be diffed."""
    _, html = page
    state = json.loads(re.search(r'id="state" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert {row["account"] for row in state} == {"Meridian Towers", "Corvus Radio"}
    meridian = next(row for row in state if row["account"] == "Meridian Towers")
    assert meridian["touches"] == [True, False, False, False, False]
    assert meridian["value_est_gbp"] == 1500


def test_the_trail_is_not_published(page):
    """It names who did what, and belongs in Cadence rather than on a shared page."""
    _, html = page
    state = json.loads(re.search(r'id="state" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert all("history" not in row for row in state)
    assert "artefact import" not in html


def test_the_rows_are_grouped_by_where_they_are_in_the_sequence(page):
    _, html = page
    # Meridian Towers has a touch fired, so it sits in `sequencing`; Corvus Radio was moved
    # to `qualified`. Neither is in `not started`, so that group is not drawn.
    assert "sequencing · 1" in html
    assert "qualified · 1" in html
    assert "not started" not in html


def test_both_themes_are_defined(page):
    """The viewer has three states, and the un-stamped one is the default."""
    _, html = page
    assert "@media (prefers-color-scheme:dark)" in html
    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    assert "body{" in html and "background:var(--ground)" in html


def test_an_unknown_tracker_is_refused_by_name():
    with pytest.raises(ValueError, match="No such tracker"):
        export.render("nonexistent")
