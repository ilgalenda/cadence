"""Acceptance bar for the score record.

This store exists for one reason: the grade thresholds were set against nine real
Leadinfo blocks, and there was no way to do better because nothing kept a score
once the page had rendered it. So the two things worth pinning are that a score
*is* kept with the features needed to re-fit the bands, and that the pasted lead
text and the contact's identity are *not* — a store that keeps more than its
purpose requires is a liability waiting for somebody to copy the directory.

The third is that filing a score can never cost you the score itself.
"""
from __future__ import annotations

import pytest

from agents.sales.store import scores as store
from agents.services import lead_scoring

BLOCK = (
    "Marta Lindqvist · marta.lindqvist@example.com\n"
    "Page views\n"
    "10:00\thttps://www.acme.example/pricing\t45s\n"
    "10:01\thttps://www.acme.example/hardware/open-time-server\t2m 10s"
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SCORES_FILE", tmp_path / "scores.json")


def _record(company: str = "Acme Bank") -> dict:
    return store.record("sam", lead_scoring.score_lead(BLOCK), company=company)


def test_a_score_is_kept_with_what_calibration_needs():
    row = _record()

    assert row["score"] == lead_scoring.score_lead(BLOCK)["score"]
    assert row["grade"] in ("A", "B", "C")
    # Each component's contribution, so a threshold can be re-fitted against the
    # shape of a session and not only its total.
    assert set(row["components"]) == {"Intent", "Depth", "Breadth"}
    # The page types and their dwell — and the URLs, because a page nobody
    # classified is the other thing this file can tell you.
    assert [v["type"] for v in row["page_views"]] == ["pricing", "product"]
    assert row["page_views"][0]["seconds"] == 45


def test_the_pasted_lead_never_reaches_the_file():
    serialised = str(_record())

    assert "marta.lindqvist@example.com" not in serialised
    assert "Marta Lindqvist" not in serialised
    assert "Page views" not in serialised


def test_scores_accumulate_newest_first():
    _record("First")
    _record("Second")

    assert [r["company"] for r in store.all_scores()] == ["Second", "First"]


def test_the_file_is_bounded(monkeypatch):
    monkeypatch.setattr(store, "MAX_SCORES", 3)
    for i in range(5):
        _record(f"Company {i}")

    kept = store.all_scores()
    assert len(kept) == 3
    # The cap drops the oldest, never the newest.
    assert [r["company"] for r in kept] == ["Company 4", "Company 3", "Company 2"]


def test_distribution_reports_the_shape_without_judging_it():
    _record()
    _record()

    shape = store.distribution()
    assert shape["count"] == 2
    assert sum(shape["by_grade"].values()) == 2
    assert shape["scores"] == sorted(shape["scores"])


def test_an_unreadable_file_does_not_lose_the_next_score(tmp_path, monkeypatch):
    corrupt = tmp_path / "scores.json"
    corrupt.write_text("{ this is not json")
    monkeypatch.setattr(store, "SCORES_FILE", corrupt)

    _record("After the corruption")

    assert [r["company"] for r in store.all_scores()] == ["After the corruption"]
