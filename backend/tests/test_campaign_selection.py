"""Tests for the deterministic Campaign Selection service."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.services import campaign_selection as cs  # noqa: E402


def test_inbound_hot_is_warm_reengagement_three_touches():
    plan = cs.select_campaign(signal_type="inbound_action", signal_strength="hot")
    assert plan.archetype == cs.WARM_INBOUND
    assert plan.channels == ["email", "linkedin"]
    assert plan.touch_count == 3
    assert plan.touch_structure == ["warm_intro", "value_add", "soft_ask"]
    assert plan.requires_identification is False


def test_inbound_touch_count_scales_with_warmth():
    warm = cs.select_campaign(signal_type="inbound_action", signal_strength="warm")
    cold = cs.select_campaign(signal_type="inbound_action", signal_strength="cold")
    assert warm.touch_count == 4
    assert warm.touch_structure[-1] == "new_angle"
    assert cold.touch_count == 5
    assert cold.touch_structure[-1] == "break_up"


def test_vertical_fit_with_contact_is_abm_no_identification():
    plan = cs.select_campaign(
        signal_type="vertical_fit", signal_strength="cold", has_named_contact=True
    )
    assert plan.archetype == cs.ABM
    assert plan.channels == ["linkedin", "email", "call"]
    assert plan.requires_identification is False
    assert plan.touch_structure == ["week1_connect", "week2_followup_email", "week3_value_add", "week4_soft_ask"]


def test_account_level_signal_requires_identification_first():
    plan = cs.select_campaign(
        signal_type="no_signal", signal_strength="warm", has_named_contact=False
    )
    assert plan.archetype == cs.ABM
    assert plan.requires_identification is True
    assert "identify" in plan.rationale.lower()


def test_all_outbound_runs_as_abm():
    for signal_type in ("vertical_fit", "no_signal"):
        plan = cs.select_campaign(signal_type=signal_type, signal_strength="cold")
        assert plan.archetype == cs.ABM


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        cs.select_campaign(signal_type="nonsense", signal_strength="hot")
    with pytest.raises(ValueError):
        cs.select_campaign(signal_type="inbound_action", signal_strength="tepid")


def test_strength_from_grade():
    assert cs.strength_from_grade("A") == "hot"
    assert cs.strength_from_grade("b") == "warm"
    assert cs.strength_from_grade(" C ") == "cold"
    with pytest.raises(ValueError):
        cs.strength_from_grade("Z")


def test_plan_is_deterministic_and_serialisable():
    a = cs.select_campaign(signal_type="inbound_action", signal_strength="hot")
    b = cs.select_campaign(signal_type="inbound_action", signal_strength="hot")
    assert a.to_dict() == b.to_dict()
    assert a.to_dict()["inputs"]["signal_strength"] == "hot"
    assert a.rationale  # non-empty explanation for the human
