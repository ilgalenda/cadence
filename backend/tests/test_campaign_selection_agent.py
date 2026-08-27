"""Acceptance bar for the Campaign Selection agent.

The *rules* are covered by `test_campaign_selection.py`, which tests the service.
This file covers the seam the agent adds, and that seam is the whole risk: Lead
scoring writes its signal type as prose (`"Inbound action"`), the service accepts
only `inbound_action` and **raises on anything else**. Get it wrong and a path step
either crashes or — worse — silently reads "no signal" and picks the wrong
archetype for a warm inbound lead.

So what is pinned here:

  * every form the scoring analysis can actually emit normalises correctly;
  * an unreadable input falls back to a *stated* default, never a raise;
  * the strength falls back through the score's own grade, so the agent and the
    service can never disagree about what a B means;
  * everything defaulted is named in `assumed`, because a plan that guessed its
    inputs and did not say so is worse than one that admits it.
"""
from __future__ import annotations

import pytest

from agents.sales.campaign_selection import agent
from agents.services import campaign_selection as rules

#: A scored verdict as `sales/scoring` returns it under `final` — note the prose
#: casing, which is what the model is instructed to produce (`prompts.py`).
SCORED_INBOUND = {
    "company": "Northgate Nordics",
    "signal_type": "Inbound action",
    "signal_strength": "hot",
    "lead_grade": "A",
    "lead_score": 82,
}

SCORED_COLD = {
    "company": "Ashford Capital",
    "signal_type": "Vertical fit",
    "lead_grade": "C",
}


# ---------------------------------------------------------------------------
# The seam — prose in, enum out
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given", [
    "inbound_action", "Inbound action", "INBOUND ACTION", "inbound-action", "  Inbound   Action  ",
])
def test_every_form_the_model_writes_normalises(given):
    assert agent.normalise_signal_type(given) == ("inbound_action", False)


@pytest.mark.parametrize("given", ["Vertical fit", "vertical_fit", "VERTICAL-FIT"])
def test_the_outbound_signal_type_normalises_too(given):
    assert agent.normalise_signal_type(given) == ("vertical_fit", False)


@pytest.mark.parametrize("given", ["no_signal", "No signal", "NO-SIGNAL"])
def test_a_stated_absence_of_signal_is_read_not_assumed(given):
    """"No signal" is a real reading of the lead, not a failure to read it."""
    assert agent.normalise_signal_type(given) == ("no_signal", False)


@pytest.mark.parametrize("given", ["", None, "something else entirely", 42, []])
def test_an_unreadable_signal_type_falls_back_rather_than_raising(given):
    """The service raises on an unknown type; this layer exists so it never sees one."""
    assert agent.normalise_signal_type(given) == ("no_signal", True)


def test_the_default_signal_type_selects_the_standing_outbound_method():
    """`no_signal` must mean ABM — "we are going after them" — not nothing."""
    plan = agent.select()
    assert plan["archetype"] == rules.ABM


@pytest.mark.parametrize("given,expected", [("hot", "hot"), ("Warm", "warm"), ("COLD", "cold")])
def test_a_stated_strength_is_taken_as_given(given, expected):
    assert agent.normalise_strength(given) == (expected, False)


def test_an_unstated_strength_falls_back_through_the_scores_own_grade():
    """Via the service's `strength_from_grade`, so the two cannot disagree."""
    assert agent.normalise_strength("", grade="A") == ("hot", True)
    assert agent.normalise_strength(None, grade="b") == ("warm", True)
    assert agent.normalise_strength("junk", grade="C") == ("cold", True)


def test_an_unusable_grade_falls_back_to_the_safe_default():
    """Cold gives the longest sequence — the safe way to be wrong."""
    assert agent.normalise_strength("", grade="Z") == ("cold", True)
    assert agent.normalise_strength("", grade=None) == ("cold", True)


# ---------------------------------------------------------------------------
# The plan, computed from a real verdict
# ---------------------------------------------------------------------------

def test_a_hot_inbound_verdict_gives_warm_reengagement_with_three_touches():
    plan = agent.select(lead=SCORED_INBOUND, has_named_contact=True)

    assert plan["archetype"] == rules.WARM_INBOUND
    assert plan["channels"] == ["email", "linkedin"]
    assert plan["touch_count"] == 3
    assert plan["requires_identification"] is False
    assert plan["assumed"] == [], "everything was read from the verdict"


def test_an_outbound_verdict_runs_as_abm_and_asks_for_identification_first():
    plan = agent.select(lead=SCORED_COLD, has_named_contact=False)

    assert plan["archetype"] == rules.ABM
    assert plan["channels"] == ["linkedin", "email", "call"]
    assert plan["requires_identification"] is True
    # Strength was absent from the verdict, so it came from grade C.
    assert plan["assumed"] == ["signal_strength"]


def test_explicit_arguments_beat_the_verdict():
    """A conversation supplies these directly; a path supplies the verdict."""
    plan = agent.select(lead=SCORED_INBOUND, signal_type="vertical_fit", has_named_contact=True)
    assert plan["archetype"] == rules.ABM


def test_everything_defaulted_is_named():
    plan = agent.select()
    assert plan["assumed"] == ["signal_type", "signal_strength", "has_named_contact"]
    assert plan["error"] is None


def test_nothing_is_assumed_when_everything_is_given():
    plan = agent.select(
        signal_type="inbound_action", signal_strength="warm", has_named_contact=True,
    )
    assert plan["assumed"] == []


def test_an_empty_verdict_still_produces_a_usable_plan():
    """A path can reach this step without having scored anything — the inbound lane
    has no scoring step at all."""
    plan = agent.select(lead={})
    assert plan["touch_structure"], "there is still a sequence to run"
    assert plan["error"] is None


def test_the_plan_carries_the_inputs_it_used():
    """The service records them; they must survive the agent's wrapping, or a plan
    cannot be explained after the fact."""
    plan = agent.select(lead=SCORED_INBOUND, has_named_contact=True)
    assert plan["inputs"] == {
        "signal_type": "inbound_action",
        "signal_strength": "hot",
        "has_named_contact": True,
    }


# ---------------------------------------------------------------------------
# From conversation
# ---------------------------------------------------------------------------

def test_the_tool_reports_the_plan_in_prose():
    text = agent.run_as_tool("sam", {
        "signal_type": "inbound_action", "signal_strength": "hot", "has_named_contact": True,
    })
    assert "warm inbound re-engagement" in text
    assert "3 touches" in text
    assert "email · linkedin" in text
    assert "warm intro" in text, "the sequence is readable, not snake_case"


def test_the_tool_says_the_choice_is_the_users():
    """Canon puts the human step at the choosing, so the tool must not sound final."""
    assert "the choice is yours" in agent.run_as_tool("sam", {})


def test_the_tool_states_what_it_assumed():
    text = agent.run_as_tool("sam", {})
    assert "Assumed: signal type, signal strength, has named contact" in text
    assert "Score the lead first" in text


def test_the_tool_says_nothing_about_assumptions_when_it_made_none():
    text = agent.run_as_tool("sam", {
        "signal_type": "vertical_fit", "signal_strength": "cold", "has_named_contact": True,
    })
    assert "Assumed" not in text


def test_the_tool_names_x_ray_when_there_is_nobody_to_write_to():
    text = agent.run_as_tool("sam", {"signal_type": "vertical_fit", "has_named_contact": False})
    assert "run X-ray first" in text


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_it_registers_as_a_read_only_tool():
    from agents.sales import tools
    from agents.sales.registry import register_all

    tools.reset_for_tests()
    try:
        register_all()
        tool = tools.get("select_campaign")
        assert tool is not None
        assert tool.writes is False, "it computes; it persists nothing"
        assert "Deterministic" in tool.description
    finally:
        tools.reset_for_tests()


def test_the_tool_schema_offers_only_what_the_rules_accept():
    """An enum the service would reject is a tool call that fails at the seam."""
    properties = agent.TOOL_SCHEMA["properties"]
    assert set(properties["signal_type"]["enum"]) == rules.SIGNAL_TYPES
    assert set(properties["signal_strength"]["enum"]) == rules.STRENGTHS
