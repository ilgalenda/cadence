"""Tests for the deterministic Duty & Tax engine.

Runs under pytest (`python -m pytest backend/tests/test_duty.py`) or directly
(`python backend/tests/test_duty.py` from the backend/ directory).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.duty import calc  # noqa: E402
from agents.duty.rates import MockDutyRateProvider  # noqa: E402


def test_cif_breakdown():
    # Goods 1000, freight 100, insurance 50, duty 5%, VAT 20%, CIF basis.
    b = calc.compute_landed_cost(
        goods_value=1000, freight=100, insurance=50,
        duty_rate=0.05, vat_rate=0.20, valuation_basis="CIF",
    )
    assert b["dutiable_value"] == 1150.0          # goods + freight + insurance
    assert b["duty"] == 57.5                       # 1150 * 5%
    assert b["vat_base"] == 1207.5                 # 1150 + 57.5 duty
    assert b["vat"] == 241.5                        # 1207.5 * 20%
    assert b["total_taxes"] == 299.0               # duty + vat
    assert b["landed_cost"] == 1449.0              # 1150 + 299


def test_fob_excludes_freight_from_duty():
    # Same numbers but FOB basis → duty only on the goods value.
    b = calc.compute_landed_cost(
        goods_value=1000, freight=100, insurance=50,
        duty_rate=0.05, vat_rate=0.20, valuation_basis="FOB",
    )
    assert b["dutiable_value"] == 1000.0
    assert b["duty"] == 50.0                        # 1000 * 5%
    # VAT base still includes freight + insurance + duty.
    assert b["vat_base"] == 1200.0                  # 1000 + 100 + 50 + 50
    assert b["vat"] == 240.0
    assert b["landed_cost"] == 1440.0               # 1150 + 50 duty + 240 vat


def test_zero_rates_are_just_logistics():
    b = calc.compute_landed_cost(goods_value=500, freight=40, duty_rate=0.0, vat_rate=0.0)
    assert b["duty"] == 0.0 and b["vat"] == 0.0
    assert b["landed_cost"] == 540.0


def test_rejects_bad_inputs():
    for kwargs in (
        {"goods_value": -1, "duty_rate": 0.1, "vat_rate": 0.1},
        {"goods_value": 100, "duty_rate": 1.5, "vat_rate": 0.1},
    ):
        try:
            calc.compute_landed_cost(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")


def test_mock_provider_known_and_default():
    p = MockDutyRateProvider()
    gb = p.lookup(destination="GB", hs_code="8517.12")  # phones, chapter 85
    assert gb["vat_rate"] == 0.20 and gb["valuation_basis"] == "CIF"
    assert gb["duty_rate"] == 0.030
    us = p.lookup(destination="US", hs_code="8471")     # computers, chapter 84
    assert us["vat_rate"] == 0.0 and us["valuation_basis"] == "FOB"
    # Unknown destination + chapter → defaults, with a note.
    xx = p.lookup(destination="ZZ", hs_code="99")
    assert xx["duty_rate"] == 0.05 and xx["vat_rate"] == 0.15
    assert "default" in xx["notes"].lower()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all duty tests passed")
