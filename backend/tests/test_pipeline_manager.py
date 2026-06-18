"""Tests for the deterministic Pipeline Manager (quiet / aging / briefing).

Runs under pytest or directly (`python backend/tests/test_pipeline_manager.py`).
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.forecast import pipeline_manager as pm  # noqa: E402
from agents.forecast.crm import MockHubSpotConnector  # noqa: E402

DEALS = MockHubSpotConnector().fetch_deals()
TODAY = date(2026, 6, 20)


def test_quiet_only_surfaces_inactive_open_deals():
    quiet = pm.quiet_deals(DEALS, TODAY)
    ids = {q["deal_id"] for q in quiet}
    assert ids == {"d4"}                      # only d4 (last activity 2026-04-02)
    assert quiet[0]["days_quiet"] == 79
    # Closed deals never appear even if long inactive.
    assert "d8" not in ids and "d9" not in ids


def test_quiet_threshold_boundary():
    # d2 last activity 2026-06-10 → 10 days quiet on 2026-06-20.
    assert {q["deal_id"] for q in pm.quiet_deals(DEALS, TODAY, days=10)} >= {"d2", "d4"}
    assert "d2" not in {q["deal_id"] for q in pm.quiet_deals(DEALS, TODAY, days=11)}


def test_aging_by_pipeline_age_and_in_stage():
    aging = {a["deal_id"]: a for a in pm.aging_deals(DEALS, TODAY)}
    assert set(aging) == {"d3", "d4", "d5"}
    assert "in pipeline" in aging["d5"]["reason"]          # aged by created_at only
    assert "qualification" in aging["d3"]["reason"]        # also stuck in stage


def test_aging_skips_deals_without_dates():
    stripped = [{k: v for k, v in d.items() if k not in ("created_at", "stage_entered_at")} for d in DEALS]
    assert pm.aging_deals(stripped, TODAY) == []


def test_briefing_structure():
    b = pm.build_briefing(DEALS, TODAY)
    assert b["date"] == "2026-06-20"
    assert b["summary"]["open_count"] == 8                 # 10 deals − 2 closed
    assert {q["deal_id"] for q in b["quiet"]} == {"d4"}
    assert {a["deal_id"] for a in b["aging"]} == {"d3", "d4", "d5"}
    assert any("d5" in i["deal_id"] for i in b["overdue"]) # d5 close date 2026-05-01 is past


def test_render_is_plain_text():
    text = pm.render_briefing_text(pm.build_briefing(DEALS, TODAY))
    assert "Pipeline morning briefing — 2026-06-20" in text
    assert "Gone quiet (1)" in text
    assert "Sitting too long (3)" in text
    assert "<" not in text                                 # plain text, no markup


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all pipeline-manager tests passed")
