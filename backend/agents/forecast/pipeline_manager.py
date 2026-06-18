from __future__ import annotations
"""Pipeline Manager — deterministic daily-review layer over the Forecasting deals.

Surfaces deals that have gone quiet (no recent activity) and deals that have sat
in the pipeline / a single stage too long, and assembles a structured morning
briefing. No LLM — every number is computed from the deal data, so the brief is
auditable and the email is free to send. Pure functions over a deal list + a
`today: date`, so it's fully unit-testable.
"""
from datetime import date
from typing import Optional

from agents.forecast import analytics
from agents.forecast.crm import OPEN_STAGES

QUIET_DAYS = 14       # no activity for at least this long → "gone quiet"
AGING_DAYS = 60       # open since created_at for longer than this → "aging"
IN_STAGE_DAYS = 30    # in the current stage longer than this → "stuck in stage"


def _parse(d: str) -> Optional[date]:
    try:
        return date.fromisoformat(d) if d else None
    except (ValueError, TypeError):
        return None


def _open(deals: list[dict]) -> list[dict]:
    return [d for d in deals if d.get("stage") in OPEN_STAGES]


def quiet_deals(deals: list[dict], today: date, days: int = QUIET_DAYS) -> list[dict]:
    """Open deals whose last activity is at least `days` old, newest-gap last."""
    out = []
    for d in _open(deals):
        last = _parse(d.get("last_activity", ""))
        if last is None:
            continue
        gap = (today - last).days
        if gap >= days:
            out.append({
                "deal_id": d.get("id", ""), "name": d.get("name", ""),
                "stage": d.get("stage", ""), "days_quiet": gap,
            })
    return sorted(out, key=lambda x: x["days_quiet"], reverse=True)


def aging_deals(deals: list[dict], today: date,
                aging_days: int = AGING_DAYS, in_stage_days: int = IN_STAGE_DAYS) -> list[dict]:
    """Open deals that have sat in the pipeline, or in their current stage, too long.

    Skips a deal silently if it carries neither `created_at` nor `stage_entered_at`
    (a real connector may not supply them).
    """
    out = []
    for d in _open(deals):
        reasons = []
        created = _parse(d.get("created_at", ""))
        if created is not None and (today - created).days > aging_days:
            reasons.append(f"in pipeline {(today - created).days}d")
        entered = _parse(d.get("stage_entered_at", ""))
        if entered is not None and (today - entered).days > in_stage_days:
            reasons.append(f"in {d.get('stage', '')} {(today - entered).days}d")
        if reasons:
            out.append({
                "deal_id": d.get("id", ""), "name": d.get("name", ""),
                "stage": d.get("stage", ""), "reason": "; ".join(reasons),
            })
    return out


def build_briefing(deals: list[dict], today: date) -> dict:
    """Assemble the full deterministic morning briefing."""
    fc = analytics.weighted_forecast(deals)
    overdue = [i for i in analytics.hygiene(deals, today) if "past" in i["issue"]]
    return {
        "date": today.isoformat(),
        "summary": {
            "open_count": len(_open(deals)),
            "open_value": fc["open_value"],
            "weighted_forecast": fc["weighted_forecast"],
            "by_stage": fc["by_stage"],
        },
        "quiet": quiet_deals(deals, today),
        "aging": aging_deals(deals, today),
        "overdue": overdue,
    }


def render_briefing_text(briefing: dict) -> str:
    """Render the briefing as a plain-text email body (no markup, no model)."""
    s = briefing["summary"]
    lines = [
        f"Pipeline morning briefing — {briefing['date']}",
        "",
        f"Open pipeline: {s['open_count']} deals · "
        f"{s['open_value']:.0f} open · {s['weighted_forecast']:.0f} weighted",
        "",
    ]

    def section(title: str, items: list[dict], fmt) -> None:
        lines.append(f"{title} ({len(items)}):")
        lines.extend(["  - " + fmt(i) for i in items] or ["  — none"])
        lines.append("")

    section("Gone quiet", briefing["quiet"],
            lambda i: f"{i['name']} [{i['stage']}] — quiet {i['days_quiet']}d")
    section("Sitting too long", briefing["aging"],
            lambda i: f"{i['name']} [{i['stage']}] — {i['reason']}")
    section("Overdue close date", briefing["overdue"],
            lambda i: f"{i['name']} — {i['issue']}")
    lines.append("— Cadence Pipeline Manager (figures from your synced pipeline; not advice)")
    return "\n".join(lines)
