"""Path resolver for Cadence's mutable state.

Every storage module routes through this.

  * `DATA_ROOT` env var, if set, is the root for all mutable state
    (vault, agent data, users.json, users_credentials.json).
  * Unset → defaults to ~/cadence-data.

Two real modes:

  - Local dev (laptop): set DATA_ROOT to a path *outside* the repo, e.g.
    DATA_ROOT=~/cadence-data. Test writes never appear in `git status`.
    Use `bin/sync-from-repo.sh` after `git pull` to refresh with the
    latest server-pushed data.

  - Production (server): DATA_ROOT points at the repo's backend/ (or
    a wrapper directory a sync cron pushes from). Writes land in the
    working tree; a cron commits + pushes data back periodically.
"""
from __future__ import annotations

import os
from pathlib import Path

# REPO_ROOT points at backend/ — this file lives at backend/paths.py.
REPO_ROOT = Path(__file__).resolve().parent


def data_root() -> Path:
    raw = os.environ.get("DATA_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "cadence-data").resolve()


# ---------------------------------------------------------------------------
# Per-component path helpers
# ---------------------------------------------------------------------------

def vault_dir() -> Path:
    return data_root() / "vault"


def users_file() -> Path:
    return data_root() / "agents" / "users.json"


def users_credentials_file() -> Path:
    return data_root() / "agents" / "users_credentials.json"


# Calls
def calls_data() -> Path:
    return data_root() / "agents" / "calls" / "data"


def calls_transcripts() -> Path:
    return calls_data() / "transcripts"


def calls_user_kb() -> Path:
    return data_root() / "agents" / "calls" / "knowledge" / "_user"


# Lead
def lead_data() -> Path:
    return data_root() / "agents" / "lead" / "data"


def lead_user_kb() -> Path:
    return data_root() / "agents" / "lead" / "knowledge" / "_user"


def lead_google_tokens() -> Path:
    return lead_data() / "google_tokens.json"


# Owl
def owl_data() -> Path:
    return data_root() / "agents" / "owl" / "data"


# High-Intent
def high_intent_data() -> Path:
    return data_root() / "agents" / "high_intent" / "data"


# Duty & Tax
def duty_data() -> Path:
    return data_root() / "agents" / "duty" / "data"


# Onboarding
def onboarding_data() -> Path:
    return data_root() / "agents" / "onboarding" / "data"


# Forecasting
def forecast_data() -> Path:
    return data_root() / "agents" / "forecast" / "data"


# >>> cadence:paths — `create_agent.py` inserts new per-agent path helpers above this line.
