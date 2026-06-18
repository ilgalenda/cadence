from __future__ import annotations
"""Onboarding storage — per-user checklist progress.

`progress` holds one record per user (id == username) tracking which curriculum
steps they've completed.
"""
from agents.shared.jsonstore import JsonCollection
from paths import onboarding_data

DATA_DIR = onboarding_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)

progress = JsonCollection(DATA_DIR, "progress", cap=1000)
