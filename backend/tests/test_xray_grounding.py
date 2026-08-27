"""How X-ray acquires the "why", which is half of what it needs.

Discovery reasons from a vertical and a product line to work out which technical
function would own timing at an account. A scored lead supplies both. A company
name typed by hand supplies neither, and the model was left inferring them
silently inside the same call that was also supposed to be finding people —
which is the weakest search this agent has ever done and the reason a
hand-typed company disappoints.

So there are three ways in and one mechanism:

  * `from_lead`     — score the pasted blob first, through the same
                      `scoring.analyse` Lead scoring runs, and use the verdict
  * `shortlist`     — a verdict handed over already scored
  * `from_company`  — derive the grounding, then search

The rule these pin is that grounding is an *improvement* on the search and never
a precondition for it: every way it can fail must cost accuracy, not the result.
"""
from __future__ import annotations

import pytest

from agents.sales.xray import agent as xray_agent


@pytest.fixture
def no_search(monkeypatch):
    """Capture what `shortlist` was grounded in, without spending a search."""
    seen: dict = {}

    def fake_shortlist(username, signal_final, structured, personas=None):
        seen['signal_final'] = signal_final
        seen['structured'] = structured
        seen['personas'] = personas
        return {
            "results": [{"full_name": "Annika Lindqvist"}],
            "grouped": {}, "raw": "", "error": None,
            "provider_errors": [], "truncated": False, "persona_source": "data_root",
        }

    monkeypatch.setattr(xray_agent, "shortlist", fake_shortlist)
    return seen


# ── A lead dropped straight onto X-ray ──────────────────────────────────────

def test_a_pasted_lead_is_scored_and_becomes_the_grounding(monkeypatch, no_search):
    verdict = {"company": "Northgate", "role": "Network Architect", "product_fit": "PTP grandmaster"}
    scored: dict = {}

    def fake_analyse(username, *, text=None, **kw):
        scored['text'] = text
        return {"final": verdict}

    monkeypatch.setattr("agents.sales.scoring.agent.analyse", fake_analyse)

    out = xray_agent.from_lead("sam", text="They downloaded the MiFID II whitepaper twice.")

    # Composed, not copied: the same scorer Lead scoring runs.
    assert scored['text'] == "They downloaded the MiFID II whitepaper twice."
    # And its verdict — not a re-derived guess — is what discovery is given.
    assert no_search['signal_final'] is verdict
    # The verdict travels back, so the page can show what grounded the search
    # without paying to score it a second time.
    assert out["lead"] is verdict
    assert len(out["results"]) == 1


def test_an_empty_lead_never_reaches_the_scorer(monkeypatch):
    monkeypatch.setattr("agents.sales.scoring.agent.analyse",
                        lambda *a, **k: pytest.fail("scored an empty lead"))

    out = xray_agent.from_lead("sam", text="   ")

    assert out["error"] == "missing_lead"
    assert out["results"] == []


def test_a_lead_with_no_company_says_so_and_still_returns_the_verdict(monkeypatch):
    # Searching for people at a company the lead never named would find nobody
    # and blame the search. The verdict is still worth reading.
    verdict = {"company": "", "role": "Unknown"}
    monkeypatch.setattr("agents.sales.scoring.agent.analyse", lambda *a, **k: {"final": verdict})

    out = xray_agent.from_lead("sam", text="Someone filled the form.")

    assert out["error"] == "lead_has_no_company"
    assert out["lead"] is verdict


# ── A bare company name ─────────────────────────────────────────────────────

def test_a_company_search_is_grounded_before_it_runs(monkeypatch, no_search):
    monkeypatch.setattr(xray_agent, "derive_grounding", lambda username, company: {
        "industry": "capital markets", "product_fit": "MiFID II clock sync", "note": "an exchange",
    })

    out = xray_agent.from_company("sam", "Northgate Nordics")

    # The derived vertical and product line reach discovery in the same fields a
    # scored lead would have filled — so a typed name is no longer a lesser search.
    assert no_search['structured']["industry"] == "capital markets"
    assert no_search['signal_final']["product_fit"] == "MiFID II clock sync"
    assert no_search['signal_final']["company"] == "Northgate Nordics"
    assert out["grounding"]["note"] == "an exchange"


def test_grounding_that_knows_nothing_leaves_the_prompt_exactly_as_bare(monkeypatch, no_search):
    # An unrecognised company must not have a vertical invented for it: a wrong
    # vertical sends the whole search after the wrong technical function, which
    # is worse than the silence it replaced.
    monkeypatch.setattr(xray_agent, "derive_grounding", lambda username, company: {
        "industry": "", "product_fit": "", "note": "",
    })

    xray_agent.from_company("sam", "Some Unknown GmbH")

    assert "industry" not in no_search['structured']
    assert "product_fit" not in no_search['signal_final']


def test_grounding_can_be_skipped_so_the_eval_measures_one_thing(monkeypatch, no_search):
    monkeypatch.setattr(xray_agent, "derive_grounding",
                        lambda *a, **k: pytest.fail("grounded when told not to"))

    xray_agent.from_company("sam", "Northgate Nordics", ground=False)

    assert no_search['signal_final'] == {"company": "Northgate Nordics"}


def test_a_company_search_with_no_company_short_circuits(monkeypatch):
    monkeypatch.setattr(xray_agent, "derive_grounding",
                        lambda *a, **k: pytest.fail("spent a call on an empty name"))

    out = xray_agent.from_company("sam", "   ")

    assert out["error"] == "missing_company"


# ── Grounding is never a precondition ───────────────────────────────────────

def test_a_failed_grounding_call_costs_accuracy_not_the_search(monkeypatch, no_search):
    def explode(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr("agents.mind.core.classify", explode)

    out = xray_agent.from_company("sam", "Northgate Nordics")

    # The search still ran, ungrounded, rather than failing on an improvement.
    assert out["error"] is None
    assert len(out["results"]) == 1
    assert out["grounding"] == {"industry": "", "product_fit": "", "note": ""}


def test_grounding_that_comes_back_as_nonsense_is_discarded(monkeypatch):
    class Result:
        text = '"just a string"'

    monkeypatch.setattr("agents.mind.core.classify", lambda **kw: Result())

    assert xray_agent.derive_grounding("sam", "Northgate") == {
        "industry": "", "product_fit": "", "note": "",
    }


def test_grounding_reads_the_three_fields_and_trims_them(monkeypatch):
    class Result:
        text = '{"industry": "  telecoms  ", "product_fit": "G.8275.1 ", "note": "", "extra": "ignored"}'

    monkeypatch.setattr("agents.mind.core.classify", lambda **kw: Result())

    assert xray_agent.derive_grounding("sam", "Telefónica") == {
        "industry": "telecoms", "product_fit": "G.8275.1", "note": "",
    }


# ── A grounding corrected by hand ───────────────────────────────────────────

def test_a_corrected_grounding_is_used_and_the_model_is_not_asked_again(monkeypatch, no_search):
    # Someone who has fixed the vertical must not be overruled on the next run.
    monkeypatch.setattr(xray_agent, "derive_grounding",
                        lambda *a, **k: pytest.fail("re-derived over a human correction"))

    out = xray_agent.from_company(
        "sam", "Northgate Nordics", None,
        grounding={"industry": "broadcast", "product_fit": "SMPTE 2110"},
    )

    assert no_search['structured']["industry"] == "broadcast"
    assert no_search['signal_final']["product_fit"] == "SMPTE 2110"
    assert out["grounding"]["industry"] == "broadcast"


def test_a_correction_that_clears_a_field_clears_it(monkeypatch, no_search):
    # Deleting a wrong vertical must actually remove it, not fall back to the
    # model's guess — otherwise the correction silently does nothing.
    monkeypatch.setattr(xray_agent, "derive_grounding",
                        lambda *a, **k: pytest.fail("re-derived over a human correction"))

    xray_agent.from_company("sam", "Northgate", None, grounding={"product_fit": "SMPTE 2110"})

    assert "industry" not in no_search['structured']
    assert no_search['signal_final']["product_fit"] == "SMPTE 2110"
