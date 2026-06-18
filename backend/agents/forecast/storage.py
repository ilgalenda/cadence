from __future__ import annotations
"""Forecasting storage — scaffolded by create_agent.py.

One capped, per-user JSON collection via the shared `JsonCollection` helper.
Add more collections (or richer records) as the agent grows.
"""
from agents.shared.jsonstore import JsonCollection
from paths import forecast_data

DATA_DIR = forecast_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)

deals = JsonCollection(DATA_DIR, "deals", cap=200)
