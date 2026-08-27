"""Where a vault write lands, and what it records about where it came from.

These pin the two defects that made the source library necessary:

1. `write_learning` chose its directory with `CALLS_DIR if agent == "calls" else
   LEAD_DIR`. A renamed agent fell through the else-branch and misfiled a month
   of learnings in silence. The destination is now a closed vocabulary, and the
   test asserts the old value *raises* rather than quietly picking a directory.
2. `write_glossary_term` recorded a call id and no title, so a term outlived any
   record of what it came from.
"""
from __future__ import annotations

import pytest

from agents.shared import vault


@pytest.fixture
def vault_dirs(tmp_path, monkeypatch):
    """Point the writers at a throwaway vault, leaving the real one alone."""
    calls = tmp_path / "dynamic" / "calls"
    lead = tmp_path / "dynamic" / "lead"
    dynamic_glossary = tmp_path / "dynamic" / "glossary"
    company_glossary = tmp_path / "company" / "glossary"
    for directory in (calls, lead, dynamic_glossary, company_glossary):
        directory.mkdir(parents=True)

    monkeypatch.setattr(vault, "CALLS_DIR", calls)
    monkeypatch.setattr(vault, "LEAD_DIR", lead)
    monkeypatch.setattr(vault, "DYNAMIC_GLOSSARY_DIR", dynamic_glossary)
    monkeypatch.setattr(vault, "GLOSSARY_DIR", company_glossary)
    monkeypatch.setattr(vault, "_LEARNING_DIRS", {"call": calls, "lead": lead})
    return {
        "calls": calls,
        "lead": lead,
        "dynamic_glossary": dynamic_glossary,
        "company_glossary": company_glossary,
    }


def _learning(**overrides):
    entry = {
        "title": "Holdover is the buying trigger",
        "description": "Holdover requirements decide the deal.",
        "content": "The estate needs 24h holdover, which rules out the incumbent.",
        "category": "technical",
        "origin": "call",
        "agent": "call_analysis",
        "contributed_by": "sam",
        "source_id": "call-1",
        "source_title": "Datacentre operator — holdover",
    }
    entry.update(overrides)
    return entry


# --- write_learning: the destination is stated, never inferred ---------------

def test_call_learning_lands_in_the_calls_directory(vault_dirs):
    path = vault.write_learning(**_learning(origin="call"))
    assert path.parent == vault_dirs["calls"]


def test_lead_learning_lands_in_the_lead_directory(vault_dirs):
    path = vault.write_learning(**_learning(origin="lead"))
    assert path.parent == vault_dirs["lead"]


def test_the_agent_name_no_longer_decides_the_directory(vault_dirs):
    """The exact defect: `call_analysis` used to mean "not calls, so leads"."""
    with pytest.raises(ValueError) as raised:
        vault.write_learning(**_learning(origin="call_analysis"))
    assert "origin must be one of" in str(raised.value)
    assert list(vault_dirs["lead"].glob("*.md")) == []


def test_an_unknown_origin_raises_rather_than_falling_back(vault_dirs):
    with pytest.raises(ValueError):
        vault.write_learning(**_learning(origin=""))


def test_a_learning_records_the_call_it_came_from(vault_dirs):
    path = vault.write_learning(**_learning())
    meta, _ = vault._parse_fm(path.read_text(encoding="utf-8"))
    assert meta["source_id"] == "call-1"
    assert meta["source_title"] == "Datacentre operator — holdover"
    assert meta["agent"] == "call_analysis"  # attribution survives, separately


# --- write_glossary_term: a term can say what it came from -------------------

def _term(**overrides):
    entry = {
        "term": "Holdover",
        "description": "How long a clock stays accurate without a reference.",
        "source_id": "call-1",
        "source_title": "Datacentre operator — holdover",
        "contributed_by": "sam",
    }
    entry.update(overrides)
    return entry


def test_a_term_records_the_name_of_its_call_not_only_the_id(vault_dirs):
    path = vault.write_glossary_term(**_term())
    meta, _ = vault._parse_fm(path.read_text(encoding="utf-8"))
    assert meta["first_seen_in"] == "call-1"
    assert meta["source_title"] == "Datacentre operator — holdover"


def test_a_term_already_in_the_company_glossary_is_still_skipped(vault_dirs):
    (vault_dirs["company_glossary"] / "holdover.md").write_text("seeded", encoding="utf-8")
    assert vault.write_glossary_term(**_term()) is None


def test_a_term_already_in_the_dynamic_glossary_is_still_skipped(vault_dirs):
    assert vault.write_glossary_term(**_term()) is not None
    assert vault.write_glossary_term(**_term()) is None
