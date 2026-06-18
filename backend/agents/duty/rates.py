from __future__ import annotations
"""Duty/VAT rate lookup for the Duty & Tax agent.

`DutyRateProvider` is the interface the agent depends on. `MockDutyRateProvider`
ships a small, GENERIC sample table (a handful of destinations × HS chapters) so
the agent is fully runnable out of the box. To go live, implement the same
interface against a real tariff/customs API (e.g. a customs-data vendor) and
swap it in `get_provider()` — nothing else changes.

Rates here are illustrative sample data, NOT customs advice.
"""
from typing import Optional, Protocol


class RateResult(dict):
    """{duty_rate, vat_rate, valuation_basis, source, notes}."""


class DutyRateProvider(Protocol):
    def lookup(self, *, destination: str, hs_code: str) -> RateResult:
        """Return duty/VAT rates for a destination (ISO-2) and HS code."""
        ...


# Per-destination standard import VAT/GST and customs valuation basis.
# (Generic public-knowledge figures; sample data only.)
_COUNTRY = {
    "US": {"vat_rate": 0.00, "basis": "FOB", "note": "No federal VAT; state sales/use tax may apply separately."},
    "GB": {"vat_rate": 0.20, "basis": "CIF"},
    "DE": {"vat_rate": 0.19, "basis": "CIF"},
    "FR": {"vat_rate": 0.20, "basis": "CIF"},
    "NL": {"vat_rate": 0.21, "basis": "CIF"},
    "AE": {"vat_rate": 0.05, "basis": "CIF"},
    "SG": {"vat_rate": 0.09, "basis": "CIF", "note": "GST."},
    "IN": {"vat_rate": 0.18, "basis": "CIF", "note": "IGST; varies by HS."},
    "BR": {"vat_rate": 0.17, "basis": "CIF", "note": "ICMS varies by state."},
    "AU": {"vat_rate": 0.10, "basis": "FOB", "note": "GST; customs value is FOB."},
}
_DEFAULT_COUNTRY = {"vat_rate": 0.15, "basis": "CIF", "note": "Destination not in sample table; default applied."}

# Duty rate by HS chapter (first 2 digits of the HS code). Illustrative.
_DUTY_BY_CHAPTER = {
    "84": 0.020,  # machinery & mechanical appliances
    "85": 0.030,  # electrical machinery & electronics
    "90": 0.025,  # optical/measuring/precision instruments
    "61": 0.120,  # apparel, knitted
    "62": 0.120,  # apparel, not knitted
    "22": 0.040,  # beverages
    "94": 0.050,  # furniture
    "39": 0.065,  # plastics
}
_DEFAULT_DUTY = 0.05  # fallback when the chapter isn't in the sample table


class MockDutyRateProvider:
    """Sample-table provider — generic, no proprietary data."""

    def lookup(self, *, destination: str, hs_code: str) -> RateResult:
        dest = (destination or "").strip().upper()[:2]
        chapter = "".join(ch for ch in (hs_code or "") if ch.isdigit())[:2]
        country = _COUNTRY.get(dest, _DEFAULT_COUNTRY)
        duty_rate = _DUTY_BY_CHAPTER.get(chapter, _DEFAULT_DUTY)
        notes = []
        if dest not in _COUNTRY:
            notes.append(f"destination '{destination}' not in sample table — default VAT applied")
        if chapter not in _DUTY_BY_CHAPTER:
            notes.append(f"HS chapter '{chapter or '??'}' not in sample table — default duty applied")
        if country.get("note"):
            notes.append(country["note"])
        return RateResult(
            duty_rate=duty_rate,
            vat_rate=country["vat_rate"],
            valuation_basis=country["basis"],
            source="MockDutyRateProvider (sample data)",
            notes="; ".join(notes),
        )


_provider: Optional[DutyRateProvider] = None


def get_provider() -> DutyRateProvider:
    """Return the configured rate provider. Swap the implementation here to go live."""
    global _provider
    if _provider is None:
        _provider = MockDutyRateProvider()
    return _provider
