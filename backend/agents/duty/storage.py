from __future__ import annotations
"""Duty & Tax storage — scaffolded by create_agent.py.

One capped, per-user JSON collection via the shared `JsonCollection` helper.
Add more collections (or richer records) as the agent grows.
"""
from agents.shared.jsonstore import JsonCollection
from paths import duty_data

DATA_DIR = duty_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)

quotes = JsonCollection(DATA_DIR, "quotes", cap=200)
