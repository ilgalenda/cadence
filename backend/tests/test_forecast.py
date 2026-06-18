"""Tests for the deterministic forecasting analytics.

Runs under pytest (`python -m pytest backend/tests/test_forecast.py`) or directly
(`python backend/tests/test_forecast.py` from the backend/ directory).
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.forecast import analytics  # noqa: E402
from agents.forecast.crm import MockHubSpotConnector  # noqa: E402

DEALS = MockHubSpotConnector().fetch_deals()


def test_open_pipeline_excludes_closed():
    fc = analytics.weighted_forecast(DEALS)
    # 8 open deals; closed_won (d8) and closed_lost (d9) excluded.
    assert fc["open_value"] == 720000.0
    assert fc["weighted_forecast"] == 270000.0


def test_group_by_vertical():
    by_v = analytics.group_by(DEALS, "vertical")
    assert by_v["Cloud"] == {"count": 3, "amount": 235000.0}
    assert by_v["Finance"]["count"] == 2
    assert "Defence" in by_v and by_v["Defence"]["amount"] == 200000.0


def test_hygiene_flags():
    issues = analytics.hygiene(DEALS, date(2026, 6, 20))
    by_deal = {(i["deal_id"], i["issue"].split()[0]) for i in issues}
    assert ("d6", "missing") in by_deal          # zero amount
    assert ("d7", "missing") in by_deal          # missing close date
    assert any(i["deal_id"] == "d5" and "past" in i["issue"] for i in issues)   # past close
    assert any(i["deal_id"] == "d4" and "activity" in i["issue"] for i in issues)  # stale
    # Closed deals are never flagged.
    assert all(i["deal_id"] not in ("d8", "d9") for i in issues)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all forecast tests passed")
