from __future__ import annotations
"""CRM connector for the Forecasting agent.

`CRMConnector` is the interface the agent depends on. `MockHubSpotConnector`
returns a small, GENERIC sample pipeline so the agent is fully runnable with no
credentials. To go live, implement the same interface against the real HubSpot
CRM API (OAuth shape mirrors `lead/google_calendar.py`) and return it from
`get_connector()` — the analytics and routes don't change.

A deal dict: {id, name, stage, amount, vertical, close_date, owner,
last_activity, created_at, stage_entered_at}. Dates are ISO (YYYY-MM-DD).
`created_at` / `stage_entered_at` drive the Pipeline Manager's "sitting too long"
detection; a real connector may omit them, in which case that check is skipped.
Sample figures are illustrative only.
"""
from typing import Optional, Protocol

# Canonical pipeline stages and their default win-probability for weighting.
STAGE_PROBABILITY = {
    "prospecting": 0.10,
    "qualification": 0.25,
    "proposal": 0.50,
    "negotiation": 0.75,
    "closed_won": 1.00,
    "closed_lost": 0.00,
}
OPEN_STAGES = [s for s in STAGE_PROBABILITY if not s.startswith("closed_")]


class CRMConnector(Protocol):
    def is_connected(self) -> bool: ...
    def fetch_deals(self) -> list[dict]: ...


# Generic sample pipeline — varied verticals/stages, a couple of deliberately
# "unhygienic" deals (missing amount, stale activity, past-due close) so the
# hygiene checks have something to find.
_SAMPLE_DEALS = [
    {"id": "d1", "name": "Acme Financial — GMC rollout", "stage": "negotiation", "amount": 120000, "vertical": "Finance", "close_date": "2026-07-15", "owner": "user1", "last_activity": "2026-06-15", "created_at": "2026-05-01", "stage_entered_at": "2026-06-10"},
    {"id": "d2", "name": "Northwind Telecom — 5G sync", "stage": "proposal", "amount": 90000, "vertical": "Telecom", "close_date": "2026-08-01", "owner": "user1", "last_activity": "2026-06-10", "created_at": "2026-05-25", "stage_entered_at": "2026-06-01"},
    {"id": "d3", "name": "Globex Defence — PNT pilot", "stage": "qualification", "amount": 200000, "vertical": "Defence", "close_date": "2026-09-30", "owner": "user2", "last_activity": "2026-06-12", "created_at": "2026-01-10", "stage_entered_at": "2026-04-15"},
    {"id": "d4", "name": "Initech Cloud — TaaS", "stage": "prospecting", "amount": 45000, "vertical": "Cloud", "close_date": "2026-10-20", "owner": "user2", "last_activity": "2026-04-02", "created_at": "2026-02-01", "stage_entered_at": "2026-03-01"},
    {"id": "d5", "name": "Umbrella Broadcast — White Rabbit", "stage": "proposal", "amount": 75000, "vertical": "Broadcast", "close_date": "2026-05-01", "owner": "user1", "last_activity": "2026-06-14", "created_at": "2026-03-01", "stage_entered_at": "2026-06-05"},
    {"id": "d6", "name": "Soylent Finance — holdover", "stage": "negotiation", "amount": 0, "vertical": "Finance", "close_date": "2026-07-25", "owner": "user2", "last_activity": "2026-06-16", "created_at": "2026-05-10", "stage_entered_at": "2026-06-10"},
    {"id": "d7", "name": "Hooli Cloud — multi-region", "stage": "qualification", "amount": 160000, "vertical": "Cloud", "close_date": "", "owner": "user1", "last_activity": "2026-06-09", "created_at": "2026-06-01", "stage_entered_at": "2026-06-02"},
    {"id": "d8", "name": "Stark Defence — quorum", "stage": "closed_won", "amount": 310000, "vertical": "Defence", "close_date": "2026-05-20", "owner": "user2", "last_activity": "2026-05-20", "created_at": "2026-02-01", "stage_entered_at": "2026-05-20"},
    {"id": "d9", "name": "Wayne Telecom — fronthaul", "stage": "closed_lost", "amount": 80000, "vertical": "Telecom", "close_date": "2026-04-30", "owner": "user1", "last_activity": "2026-04-30", "created_at": "2026-02-15", "stage_entered_at": "2026-04-30"},
    {"id": "d10", "name": "Pied Piper Cloud — edge sync", "stage": "prospecting", "amount": 30000, "vertical": "Cloud", "close_date": "2026-11-15", "owner": "user2", "last_activity": "2026-06-11", "created_at": "2026-06-05", "stage_entered_at": "2026-06-05"},
]


class MockHubSpotConnector:
    """Sample-pipeline connector — generic, no proprietary data."""

    def is_connected(self) -> bool:
        return True

    def fetch_deals(self) -> list[dict]:
        return [dict(d) for d in _SAMPLE_DEALS]


_connector: Optional[CRMConnector] = None


def get_connector() -> CRMConnector:
    """Return the configured CRM connector. Swap the implementation here to go live."""
    global _connector
    if _connector is None:
        _connector = MockHubSpotConnector()
    return _connector
