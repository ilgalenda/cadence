from __future__ import annotations
"""Deterministic pipeline analytics for the Forecasting agent.

Pure functions over a list of deal dicts (see crm.py) — no LLM, no I/O — so the
numbers are auditable and unit-testable. `today` is passed in so hygiene checks
are deterministic.
"""
from datetime import date

from agents.forecast.crm import OPEN_STAGES, STAGE_PROBABILITY

STALE_DAYS = 30


def _is_open(deal: dict) -> bool:
    return deal.get("stage") in OPEN_STAGES


def _amount(deal: dict) -> float:
    try:
        return float(deal.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def group_by(deals: list[dict], key: str) -> dict[str, dict]:
    """Sum count + amount of OPEN deals grouped by `key` (e.g. 'vertical', 'stage')."""
    out: dict[str, dict] = {}
    for d in deals:
        if not _is_open(d):
            continue
        k = d.get(key) or "Unspecified"
        bucket = out.setdefault(k, {"count": 0, "amount": 0.0})
        bucket["count"] += 1
        bucket["amount"] += _amount(d)
    return out


def weighted_forecast(deals: list[dict], probabilities: dict[str, float] | None = None) -> dict:
    """Open pipeline value and probability-weighted forecast, plus per-stage split."""
    probs = probabilities or STAGE_PROBABILITY
    open_value = 0.0
    weighted = 0.0
    by_stage: dict[str, dict] = {}
    for d in deals:
        if not _is_open(d):
            continue
        amt = _amount(d)
        p = probs.get(d.get("stage", ""), 0.0)
        open_value += amt
        weighted += amt * p
        bucket = by_stage.setdefault(d.get("stage", "unknown"), {"count": 0, "amount": 0.0, "weighted": 0.0})
        bucket["count"] += 1
        bucket["amount"] += amt
        bucket["weighted"] += amt * p
    return {
        "open_value": round(open_value, 2),
        "weighted_forecast": round(weighted, 2),
        "by_stage": {k: {"count": v["count"], "amount": round(v["amount"], 2), "weighted": round(v["weighted"], 2)} for k, v in by_stage.items()},
    }


def _parse(d: str):
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def hygiene(deals: list[dict], today: date) -> list[dict]:
    """Flag open deals with data-quality problems. Returns a list of issues."""
    issues: list[dict] = []
    for d in deals:
        if not _is_open(d):
            continue
        name = d.get("name", d.get("id", "?"))
        did = d.get("id", "")
        if _amount(d) <= 0:
            issues.append({"deal_id": did, "name": name, "issue": "missing or zero amount"})
        close = _parse(d.get("close_date", ""))
        if d.get("close_date", "") == "" or close is None:
            issues.append({"deal_id": did, "name": name, "issue": "missing close date"})
        elif close < today:
            issues.append({"deal_id": did, "name": name, "issue": f"close date {d['close_date']} is in the past"})
        last = _parse(d.get("last_activity", ""))
        if last is not None and (today - last).days > STALE_DAYS:
            issues.append({"deal_id": did, "name": name, "issue": f"no activity for {(today - last).days} days"})
    return issues
