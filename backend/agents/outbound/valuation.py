"""What an account is worth on first contract — arithmetic, never judgement.

The model classifies an account's **deal**; this module prices it. That split is the
point. A first-deal figure a language model produced is a number nobody can check,
and the figure it most often gets wrong is the one that matters most: whether
Acme arrives as the **primary grandmaster** or as a **brownfield backup**
alongside existing sync. That distinction is worth roughly eight times on first
contract, so it is a classification the caller must state and this module refuses to
guess.

**A deal is line items, not one shape.** Reverse-checking the figures already
recorded against real accounts shows why: a two-substation TSO pilot is *two*
defence-grade quorums plus support, and a colocation deal is a quorum plus a Sync
Insight subscription whose price falls with volume. A single-shape model can price
none of those, so a deal here is a list of ``(shape, quantity)`` lines, an optional
support line, and optional Fleet Insight units.

**The catalogue is not in this repository.** List prices are commercially
confidential, so they live under ``DATA_ROOT`` with every other piece of mutable
state — ``paths.outbound_pricing_file()``. ``pricing.example.json`` ships beside
this module to document the shape with obviously-fake figures.

**An absent catalogue is a supported state, not an error.** A clone with no
catalogue prices nothing: every row comes back unpriced *and says why*, which is
honest, whereas a zero reads as "this account is worth nothing" and a default reads
as a price. Nothing here raises on a missing or malformed file.

**No shape ever falls back to another.** An unrecognised shape leaves the whole deal
unpriced with its own reason. A near-miss silently priced as its neighbour is the
failure this module exists to prevent — a wrong £2,000 is worse than a visible gap.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from paths import outbound_pricing_file

#: Why a deal has no figure. Distinct values because they need different fixes: a
#: catalogue is a machine to configure, a shape is a classification to correct.
NO_CATALOGUE = "no_catalogue"
UNKNOWN_SHAPE = "unknown_shape"
NO_LINES = "no_lines"
BAD_QUANTITY = "bad_quantity"
UNKNOWN_SYNC_TIER = "unknown_sync_tier"


@dataclass(frozen=True)
class Line:
    """One priced component of a deal: a catalogue shape and how many of it."""

    shape: str
    quantity: int = 1


@dataclass(frozen=True)
class Deal:
    """How an account's first contract is put together.

    ``attach_support`` is the caller's decision, not the shape's. The same primary
    quorum is £1,000 without support and £1,500 with it, and which of those is
    right depends on the account rather than on the hardware — so it is asked for
    here and never inferred.

    ``fleet_insight_units`` prices the subscription from the catalogue's volume
    curve. Zero means the deal does not include it.
    """

    lines: tuple[Line, ...] = ()
    attach_support: bool = False
    fleet_insight_units: int = 0


@dataclass(frozen=True)
class Valuation:
    """One account's first-deal figure, and the reasoning behind it.

    ``value_gbp`` is ``None`` when the deal could not be priced — never ``0``,
    which is a price. ``unpriced_reason`` is set exactly when ``value_gbp`` is
    ``None``, so a caller cannot read one without the other. ``breakdown`` names
    every component that went into the figure, so it can be argued with.
    """

    value_gbp: Optional[int]
    note: str
    breakdown: tuple[str, ...] = ()
    support_attached: bool = False
    unpriced_reason: Optional[str] = None
    unpriced_detail: str = ""

    @property
    def is_priced(self) -> bool:
        return self.value_gbp is not None


def load_catalogue(path: Optional[Path] = None) -> Optional[dict]:
    """The catalogue, or ``None`` when there is not a usable one.

    Forgiving on read for the reason ``store/_json.py`` gives: a hand-edited file
    must not take down the surface that would let you fix it. A file that parses
    but carries no ``shapes`` is treated as absent — it can price nothing, and "no
    catalogue" is more use than "unknown shape" repeated on every row.
    """
    target = path or outbound_pricing_file()
    if not target.exists():
        return None
    try:
        catalogue = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("shapes"), dict):
        return None
    return catalogue


def shape_names(catalogue: Optional[dict]) -> list[str]:
    """The shapes this catalogue can price, sorted. Empty when there is none."""
    if not catalogue:
        return []
    return sorted(catalogue["shapes"])


def value(deal: Deal, *, catalogue: Optional[dict] = None) -> Valuation:
    """Price a deal, or say precisely why it cannot be priced."""
    if not deal.lines and not deal.fleet_insight_units:
        return _unpriced(NO_LINES, "", "No deal composition recorded, so no first-deal figure.")

    if catalogue is None:
        catalogue = load_catalogue()
    if catalogue is None:
        return _unpriced(NO_CATALOGUE, "", "No price catalogue available, so this account is unpriced.")

    total = 0
    breakdown: list[str] = []

    for line in deal.lines:
        shape = (line.shape or "").strip()
        entry = catalogue["shapes"].get(shape)
        if not isinstance(entry, dict) or not isinstance(entry.get("price_gbp"), int):
            return _unpriced(
                UNKNOWN_SHAPE, shape, f"{shape or '(blank)'} is not a shape this catalogue prices."
            )
        if not isinstance(line.quantity, int) or line.quantity < 1:
            return _unpriced(
                BAD_QUANTITY, shape, f"{shape} has a quantity of {line.quantity!r}, which cannot be priced."
            )

        unit = entry["price_gbp"]
        total += unit * line.quantity
        breakdown.append(_line_note(entry, shape, unit, line.quantity))

    support = 0
    if deal.attach_support and _any_enterprise_grade(catalogue, deal.lines):
        support = _support_price(catalogue)
        if support:
            total += support
            breakdown.append(f"Standard support £{support:,}/yr")

    if deal.fleet_insight_units:
        subscription = _fleet_insight_price(catalogue, deal.fleet_insight_units)
        if subscription is None:
            return _unpriced(
                UNKNOWN_SYNC_TIER,
                str(deal.fleet_insight_units),
                f"The catalogue has no Fleet Insight tier for {deal.fleet_insight_units} units.",
            )
        total += subscription
        breakdown.append(f"Fleet Insight, {deal.fleet_insight_units} units, £{subscription:,}/yr")

    return Valuation(
        value_gbp=total,
        note=" · ".join(breakdown),
        breakdown=tuple(breakdown),
        support_attached=support > 0,
    )


def _unpriced(reason: str, detail: str, note: str) -> Valuation:
    return Valuation(value_gbp=None, note=note, unpriced_reason=reason, unpriced_detail=detail)


def _any_enterprise_grade(catalogue: dict, lines: tuple[Line, ...]) -> bool:
    """Whether a support line may attach to this deal at all.

    Support belongs to an enterprise-grade proposal. A deal made only of portables
    — one mini appliance per outside-broadcast vehicle — is a project budget line,
    not a supported estate, and attaching £500 to it would inflate the forecast
    in exactly the direction the recorded corrections warn about.
    """
    for line in lines:
        entry = catalogue["shapes"].get((line.shape or "").strip())
        if isinstance(entry, dict) and entry.get("enterprise_grade"):
            return True
    return False


def _support_price(catalogue: dict) -> int:
    """The Standard support line, or nothing when the catalogue omits it."""
    support = catalogue.get("support")
    if not isinstance(support, dict):
        return 0
    standard = support.get("standard_gbp_per_year")
    return standard if isinstance(standard, int) else 0


def _fleet_insight_price(catalogue: dict, units: int) -> Optional[int]:
    """The annualised Fleet Insight figure for a unit count, or ``None``.

    Priced off the catalogue's stated tiers rather than interpolated. The curve
    falls with volume, so inventing a figure between two tiers would quietly
    invent a discount nobody has agreed.
    """
    tiers = catalogue.get("fleet_insight_annual_gbp")
    if not isinstance(tiers, dict):
        return None
    price = tiers.get(str(units))
    return price if isinstance(price, int) else None


def _line_note(entry: dict, shape: str, unit: int, quantity: int) -> str:
    """One clause naming what was priced and at what unit figure."""
    composition = str(entry.get("composition") or shape).strip()
    if quantity == 1:
        return f"{composition} £{unit:,}"
    return f"{quantity}× {composition} £{unit:,} each"
