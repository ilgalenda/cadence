"""Acceptance bar for the GTM agent.

The gap this file closes is the one that let GTM ship broken: nothing asserted the
*shape* of what `identify` returns, so an agent wired to the wrong prompt returned
a clean 200 carrying an ABM contact plan, and every consumer — the page, the guided
path, the Owl tool — read `final.companies`, found nothing, and reported "no
results" for weeks.

So, like the other characterisation tests, this asserts the request shape and the
response contract rather than model output:

  * `final` **always** carries `companies` and `notes`, whatever the model returns —
    a wrong shape degrades to an empty list, never to a missing key;
  * the turn is grounded: web search is asked for, and the vertical, the seed
    company and the notes all reach the prompt;
  * an incomplete turn yields whatever was parsed *plus* `error`, rather than
    raising and wasting the searches already paid for;
  * the refiner is not paid for an empty list, and can never add a company;
  * from conversation, an empty result and a failed search give different answers —
    blaming the query for a broken search is how this bug hid.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.sales import prompts
from agents.sales.gtm import agent

TARGETS_JSON = {
    "companies": [
        {
            "name": "Northgate Nordics",
            "domain": "northgate.com",
            "rationale": "Operates a trading venue under MiFID II timestamping obligations.",
            "signal": "Migrating matching engines in 2027.",
            "sources": ["https://example.com/tender"],
        },
        {
            "name": "Vantage Exchange Dublin",
            "domain": "vantage-exchange.com",
            "rationale": "Regulated venue with colocation customers.",
            "signal": "",
            "sources": ["https://example.com/vantage-exchange"],
        },
    ],
    "notes": "Scoped to Nordic and Irish venues; excluded broker-dealers.",
}


@pytest.fixture
def turn(monkeypatch):
    """Capture the model call's arguments and serve a canned shortlist.

    Set `_raw` to hand back a literal string instead — that is how the
    unparseable-answer paths are exercised.
    """
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        if "_raw" in captured:
            return SimpleNamespace(text=captured["_raw"])
        return SimpleNamespace(text=json.dumps(captured.get("_result", TARGETS_JSON)))

    monkeypatch.setattr(agent.mind, "analyze", fake)
    return captured


@pytest.fixture
def refiner(monkeypatch):
    """Record refine calls and pass pass-1 straight through by default."""
    calls: list[tuple] = []

    class FakeRefiner:
        def __init__(self, username):
            self.username = username

        def refine(self, task, claude_output, context):
            calls.append((task, claude_output, context))
            return calls_result[0] if calls_result else claude_output

    calls_result: list = []
    monkeypatch.setattr(agent, "OwlRefiner", FakeRefiner)
    return {"calls": calls, "returns": calls_result}


# ---------------------------------------------------------------------------
# The contract every consumer reads
# ---------------------------------------------------------------------------


def test_final_carries_companies(turn, refiner):
    """The assertion whose absence let the wrong prompt ship."""
    out = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert "companies" in out["final"], "every consumer reads final.companies"
    assert [c["name"] for c in out["final"]["companies"]] == ["Northgate Nordics", "Vantage Exchange Dublin"]
    assert out["final"]["notes"]
    assert out["error"] is None


def test_a_wrong_shape_degrades_to_an_empty_list(turn, refiner):
    """An ABM plan — the exact payload that caused the bug — must not lose the key."""
    turn["_result"] = {"boolean_primary": "…", "personas": [], "lusha_checklist": []}

    out = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert out["final"] == {"companies": [], "notes": ""}


@pytest.mark.parametrize("result", [None, [], "companies: none", {"companies": "Northgate"}])
def test_no_model_answer_can_raise(turn, refiner, result):
    turn["_result"] = result

    out = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert out["final"]["companies"] == []


def test_empty_entries_are_dropped(turn, refiner):
    turn["_result"] = {"companies": [{"name": "Real Co"}, None, {}, "", "Bare Name"], "notes": ""}

    companies = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)["final"]["companies"]

    assert companies == [{"name": "Real Co"}, "Bare Name"]


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def test_the_call_uses_no_tools(turn, refiner):
    """Speed is the whole reason this step is ungrounded — a tool would undo it."""
    agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert "tools" not in turn and "tool_choice" not in turn
    assert turn["max_tokens"] == agent.MAX_TOKENS


def test_the_prompt_is_honest_about_being_unverified(turn, refiner):
    """An ungrounded list that presents itself as checked is the dangerous version."""
    assert "no web access" in prompts.GTM_TARGETS_SYSTEM
    assert "caveat" in prompts.GTM_TARGETS_SYSTEM
    assert "No invented specifics" in prompts.GTM_TARGETS_SYSTEM


def test_the_request_reaches_the_prompt(turn, refiner):
    analysis = {
        "vertical": "private 5G",
        "seed_company": "Halden Engineering",
        "notes": "Canada only, public safety",
    }

    agent.identify("sam", analysis, {}, use_signals=False)

    message = turn["messages"][0]["content"]
    assert "private 5G" in message
    assert "Halden Engineering" in message
    assert "Canada only, public safety" in message, "the steer, including any Signals digest"


# ---------------------------------------------------------------------------
# A turn that stopped early
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "Sorry, I cannot help with that.", "{\"companies\": ["])
def test_an_unparseable_answer_is_reported_not_raised(turn, refiner, raw):
    """A 500 tells the user only that something broke; `error` says what."""
    turn["_raw"] = raw

    out = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert out["final"]["companies"] == []
    assert out["error"].startswith("parse_failed")


def test_a_fenced_answer_still_parses(turn, refiner):
    """Models fence JSON despite being told not to; the shared parser strips it."""
    turn["_raw"] = "```json\n" + json.dumps(TARGETS_JSON) + "\n```"

    out = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert len(out["final"]["companies"]) == 2
    assert out["error"] is None


# ---------------------------------------------------------------------------
# The refinement pass
# ---------------------------------------------------------------------------


def test_the_refiner_is_not_paid_for_an_empty_list(turn, refiner):
    turn["_result"] = {"companies": [], "notes": "nothing fits"}

    out = agent.identify("sam", {"vertical": "underwater basket weaving"}, {}, use_signals=False)

    assert refiner["calls"] == [], "refining nothing costs a Sonnet call and cannot add a company"
    assert out["owl_applied"] is False


def test_the_refiner_runs_under_its_own_task_key(turn, refiner):
    agent.identify("sam", {"vertical": "finance"}, {"tone": "direct"}, use_signals=False)

    task, claude_output, context = refiner["calls"][0]
    assert task == "gtm_targets", "the ABM key would silently no-op in refine.py"
    assert claude_output["companies"]
    assert context["analysis"]["vertical"] == "finance"
    assert context["config"] == {"tone": "direct"}


def test_a_refiner_that_breaks_the_shape_cannot_break_the_contract(turn, refiner):
    refiner["returns"].append({"boolean_primary": "…"})

    out = agent.identify("sam", {"vertical": "finance"}, {}, use_signals=False)

    assert out["final"] == {"companies": [], "notes": ""}
    assert out["claude_raw"]["companies"], "pass 1 is still reported"


# ---------------------------------------------------------------------------
# From conversation
# ---------------------------------------------------------------------------


def test_the_tool_asks_for_a_scope_before_searching(turn, refiner):
    out = agent.run_as_tool("sam", {"vertical": "", "seed_company": ""})

    assert "vertical" in out
    assert turn == {}, "no search is paid for without a scope"


def test_the_tool_renders_the_companies(turn, refiner, monkeypatch):
    monkeypatch.setattr(agent, "_with_signals", lambda username, analysis: analysis)

    out = agent.run_as_tool("sam", {"vertical": "finance"})

    assert "2 candidates for finance" in out
    assert "Northgate Nordics — Operates a trading venue" in out
    assert "Unverified" in out, "a recalled list must not present itself as checked"


def test_the_tool_does_not_blame_the_query_for_a_failed_search(turn, refiner, monkeypatch):
    """The message that hid this bug: a schema fault reported as a narrow vertical."""
    monkeypatch.setattr(agent, "_with_signals", lambda username, analysis: analysis)
    turn["_raw"] = "not json at all"

    out = agent.run_as_tool("sam", {"vertical": "finance"})

    assert "did not come back cleanly" in out
    assert "widening the vertical" not in out


def test_a_genuinely_empty_result_still_advises_widening(turn, refiner, monkeypatch):
    monkeypatch.setattr(agent, "_with_signals", lambda username, analysis: analysis)
    turn["_result"] = {"companies": [], "notes": ""}

    out = agent.run_as_tool("sam", {"vertical": "underwater basket weaving"})

    assert "widening the vertical" in out


def test_a_caveat_reaches_the_conversation(turn, refiner, monkeypatch):
    """The doubt is the useful part; dropping it would make the list look checked."""
    monkeypatch.setattr(agent, "_with_signals", lambda username, analysis: analysis)
    turn["_result"] = {
        "companies": [{"name": "Old Co", "rationale": "Runs a venue.", "caveat": "may have been acquired"}],
        "notes": "",
    }

    out = agent.run_as_tool("sam", {"vertical": "finance"})

    assert "unsure: may have been acquired" in out
