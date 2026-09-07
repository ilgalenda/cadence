"""The acceptance bar for outbound valuation.

Four rules carry the design, and each has a test that would fail if somebody
quietly relaxed it:

  * **A deal is line items.** Two of something costs twice as much, and a
    subscription and a support line are separate components — because the figures
    already recorded against real accounts decompose exactly that way and a
    single-shape model can reproduce none of them.
  * **Support is the caller's decision, floored by the catalogue.** The same
    quorum is sold with and without it, so it is asked for per account; but it can
    never attach to a deal that is only portables.
  * **Nothing falls back.** An unrecognised shape, an impossible quantity or a
    Fleet Insight volume the catalogue has no tier for leaves the deal *unpriced*
    with its own reason. A near-miss priced as its neighbour is the failure this
    module exists to prevent.
  * **Unpriced is not zero.** ``value_gbp`` is ``None`` and a reason is always set
    with it, so no caller can read a gap as "worth nothing".

**The figures here are fixtures, not prices.** The real catalogue is commercially
confidential and lives under ``DATA_ROOT``; these tests prove the arithmetic, and
the real figures are checked once against real accounts when the tracker is
imported.
"""
from __future__ import annotations

import json

import pytest

from agents.outbound import valuation
from agents.outbound.valuation import Deal, Line

#: A catalogue whose numbers are chosen so every total is unambiguous — no two
#: combinations of these add to the same figure, so a wrong answer names its own
#: cause.
CATALOGUE = {
    "currency": "GBP",
    "shapes": {
        "primary_quorum": {"composition": "3x rubidium plus rack", "price_gbp": 1000, "enterprise_grade": True},
        "defence_grade_quorum": {"composition": "3x rubidium plus", "price_gbp": 2000, "enterprise_grade": True},
        "brownfield_backup": {"composition": "1x rubidium into existing sync", "price_gbp": 300, "enterprise_grade": True},
        "portable": {"composition": "1x mini per vehicle", "price_gbp": 100, "enterprise_grade": False},
    },
    "support": {"standard_gbp_per_year": 500},
    "fleet_insight_annual_gbp": {"50": 900, "100": 1600},
}


def price(deal: Deal) -> valuation.Valuation:
    """Price against the fixture catalogue, never the machine's real one."""
    return valuation.value(deal, catalogue=CATALOGUE)


# ---------------------------------------------------------------------------
# A deal is line items
# ---------------------------------------------------------------------------

def test_a_single_line_is_its_own_price():
    assert price(Deal(lines=(Line("primary_quorum"),))).value_gbp == 1000


def test_quantity_multiplies():
    """A two-substation pilot is two quorums. This is the lever the plan relies on."""
    assert price(Deal(lines=(Line("defence_grade_quorum", 2),))).value_gbp == 4000


def test_lines_sum():
    deal = Deal(lines=(Line("primary_quorum"), Line("brownfield_backup", 2)))
    assert price(deal).value_gbp == 1600


def test_a_subscription_and_a_support_line_are_separate_components():
    """The shape that the recorded colocation figures decompose into."""
    deal = Deal(lines=(Line("primary_quorum"),), attach_support=True, fleet_insight_units=100)
    assert price(deal).value_gbp == 1000 + 500 + 1600


def test_the_breakdown_names_every_component():
    deal = Deal(lines=(Line("defence_grade_quorum", 2),), attach_support=True)
    result = price(deal)
    assert len(result.breakdown) == 2
    assert "2×" in result.breakdown[0]
    assert "support" in result.breakdown[1].lower()


# ---------------------------------------------------------------------------
# Support is the caller's decision, floored by the catalogue
# ---------------------------------------------------------------------------

def test_support_is_not_attached_unless_asked():
    """The 8x swing's smaller sibling: the same quorum, two legitimate figures."""
    without = price(Deal(lines=(Line("primary_quorum"),)))
    with_support = price(Deal(lines=(Line("primary_quorum"),), attach_support=True))
    assert without.value_gbp == 1000
    assert with_support.value_gbp == 1500
    assert without.support_attached is False
    assert with_support.support_attached is True


def test_support_cannot_attach_to_a_portables_only_deal():
    """A project budget line is not a supported estate."""
    result = price(Deal(lines=(Line("portable", 8),), attach_support=True))
    assert result.value_gbp == 800
    assert result.support_attached is False


def test_support_attaches_when_any_line_is_enterprise_grade():
    deal = Deal(lines=(Line("portable", 8), Line("primary_quorum")), attach_support=True)
    assert price(deal).value_gbp == 800 + 1000 + 500


def test_a_catalogue_with_no_support_line_prices_the_hardware():
    catalogue = {**CATALOGUE}
    catalogue.pop("support")
    result = valuation.value(Deal(lines=(Line("primary_quorum"),), attach_support=True), catalogue=catalogue)
    assert result.value_gbp == 1000
    assert result.support_attached is False


# ---------------------------------------------------------------------------
# Nothing falls back
# ---------------------------------------------------------------------------

def test_an_unknown_shape_is_unpriced_and_not_priced_as_a_neighbour():
    result = price(Deal(lines=(Line("primary_quorum_v2"),)))
    assert result.value_gbp is None
    assert result.unpriced_reason == valuation.UNKNOWN_SHAPE
    assert result.unpriced_detail == "primary_quorum_v2"


def test_one_unknown_line_leaves_the_whole_deal_unpriced():
    """A partial total is a wrong total, and a wrong total gets acted on."""
    deal = Deal(lines=(Line("primary_quorum"), Line("nonsense")))
    assert price(deal).value_gbp is None


@pytest.mark.parametrize("quantity", [0, -1, 1.5, None])
def test_an_impossible_quantity_is_unpriced(quantity):
    result = price(Deal(lines=(Line("primary_quorum", quantity),)))
    assert result.value_gbp is None
    assert result.unpriced_reason == valuation.BAD_QUANTITY


def test_a_fleet_insight_volume_with_no_tier_is_not_interpolated():
    """Inventing a figure between two tiers invents a discount nobody agreed."""
    result = price(Deal(lines=(Line("primary_quorum"),), fleet_insight_units=75))
    assert result.value_gbp is None
    assert result.unpriced_reason == valuation.UNKNOWN_SYNC_TIER


def test_a_deal_with_no_composition_is_unpriced():
    result = price(Deal())
    assert result.value_gbp is None
    assert result.unpriced_reason == valuation.NO_LINES


def test_a_blank_shape_is_unpriced_rather_than_ignored():
    result = price(Deal(lines=(Line(""),)))
    assert result.value_gbp is None
    assert result.unpriced_reason == valuation.UNKNOWN_SHAPE


# ---------------------------------------------------------------------------
# Unpriced is not zero
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "deal",
    [
        Deal(),
        Deal(lines=(Line("nonsense"),)),
        Deal(lines=(Line("primary_quorum", 0),)),
        Deal(lines=(Line("primary_quorum"),), fleet_insight_units=75),
    ],
)
def test_a_reason_is_set_exactly_when_there_is_no_figure(deal):
    result = price(deal)
    assert (result.value_gbp is None) == (result.unpriced_reason is not None)
    assert result.is_priced is False
    assert result.note


def test_a_priced_deal_carries_no_reason():
    result = price(Deal(lines=(Line("primary_quorum"),)))
    assert result.unpriced_reason is None
    assert result.is_priced is True


# ---------------------------------------------------------------------------
# The catalogue itself
# ---------------------------------------------------------------------------

def test_an_absent_catalogue_prices_nothing_and_says_so(tmp_path):
    """A clone with no catalogue must work, not crash and not guess."""
    assert valuation.load_catalogue(tmp_path / "nothing.json") is None
    result = valuation.value(Deal(lines=(Line("primary_quorum"),)), catalogue=None)
    if result.is_priced:
        pytest.skip("this machine has a real catalogue; the absent-file case is covered above")
    assert result.unpriced_reason == valuation.NO_CATALOGUE


def test_a_malformed_catalogue_is_treated_as_absent(tmp_path):
    broken = tmp_path / "pricing.json"
    broken.write_text("{ this is not json")
    assert valuation.load_catalogue(broken) is None


def test_a_catalogue_without_shapes_is_treated_as_absent(tmp_path):
    empty = tmp_path / "pricing.json"
    empty.write_text(json.dumps({"currency": "GBP", "support": {"standard_gbp_per_year": 500}}))
    assert valuation.load_catalogue(empty) is None


def test_the_shipped_example_is_a_valid_catalogue():
    """The documented shape must be loadable, or it documents nothing."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "agents" / "outbound" / "pricing.example.json"
    catalogue = valuation.load_catalogue(example)
    assert catalogue is not None
    assert "primary_quorum" in valuation.shape_names(catalogue)
    priced = valuation.value(Deal(lines=(Line("primary_quorum"),)), catalogue=catalogue)
    assert priced.is_priced


def test_shape_names_are_empty_without_a_catalogue():
    assert valuation.shape_names(None) == []
