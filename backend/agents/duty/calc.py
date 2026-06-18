from __future__ import annotations
"""Deterministic landed-cost engine for the Duty & Tax agent.

All money in the same currency (the caller's). Rates are fractions (0.05 = 5%).
The maths is intentionally simple and explicit so a quote can be audited line by
line — the autonomous agent calls `compute_landed_cost` as a tool, but the
numbers never come from the model.
"""
from typing import Literal

ValuationBasis = Literal["CIF", "FOB"]


def _round(x: float) -> float:
    return round(x + 0.0, 2)


def compute_landed_cost(
    *,
    goods_value: float,
    freight: float = 0.0,
    insurance: float = 0.0,
    duty_rate: float,
    vat_rate: float,
    valuation_basis: ValuationBasis = "CIF",
    other_fees: float = 0.0,
    currency: str = "USD",
) -> dict:
    """Return a fully itemised landed-cost breakdown.

    - Duty is charged on the customs (dutiable) value. Under **CIF** valuation
      that value includes international freight + insurance; under **FOB** it is
      the goods value alone.
    - Import VAT/GST is charged on the full landed value plus the duty
      (goods + freight + insurance + duty + other fees) — the common treatment.
    """
    if goods_value < 0 or freight < 0 or insurance < 0 or other_fees < 0:
        raise ValueError("monetary inputs must be non-negative")
    if not (0 <= duty_rate <= 1) or not (0 <= vat_rate <= 1):
        raise ValueError("rates must be fractions between 0 and 1")

    dutiable_value = goods_value + (freight + insurance if valuation_basis == "CIF" else 0.0)
    duty = dutiable_value * duty_rate
    vat_base = goods_value + freight + insurance + duty + other_fees
    vat = vat_base * vat_rate
    total_taxes = duty + vat + other_fees
    landed_cost = goods_value + freight + insurance + total_taxes

    return {
        "currency": currency,
        "valuation_basis": valuation_basis,
        "inputs": {
            "goods_value": _round(goods_value),
            "freight": _round(freight),
            "insurance": _round(insurance),
            "other_fees": _round(other_fees),
            "duty_rate": duty_rate,
            "vat_rate": vat_rate,
        },
        "dutiable_value": _round(dutiable_value),
        "duty": _round(duty),
        "vat_base": _round(vat_base),
        "vat": _round(vat),
        "total_taxes": _round(total_taxes),
        "landed_cost": _round(landed_cost),
    }
