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


# Calls. `agents/calls` was retired in Stage 4 and its work is now Call Analysis,
# Recap and Knowledge Capture under `agents/sales`, with the quizzes under
# `agents/learn`. The directories keep their names for the reason given below.
# `calls_transcripts()` went with `agents/meet` in the same slice — nothing stores a
# transcript separately now that the analysis keeps its own.
def calls_data() -> Path:
    return data_root() / "agents" / "calls" / "data"


def calls_user_kb() -> Path:
    return data_root() / "agents" / "calls" / "knowledge" / "_user"


# Sales (the redesigned front half). `agents/high_intent` was retired into it in
# R4 and `agents/lead` in Stage 3.3 — both packages are now gone. The directories
# are deliberately unchanged from the modules they replaced: renaming the accessor
# is a code change, moving the data is not, and a live snapshot should never be
# rewritten just to match a package name. So `sales_data()` still resolves under
# `lead/` and `sales_signals_data()` under `high_intent/`, and the only thing left
# in either directory is data.
def sales_data() -> Path:
    return data_root() / "agents" / "lead" / "data"


def sales_user_kb() -> Path:
    return data_root() / "agents" / "lead" / "knowledge" / "_user"


def sales_google_tokens() -> Path:
    return sales_data() / "google_tokens.json"


# Signals — the high-intent side of sales. Always sandboxed; see
# `agents.sales.store.signals` for why that rule is preserved.
def sales_signals_data() -> Path:
    return data_root() / "agents" / "high_intent" / "data"



# Owl
def owl_data() -> Path:
    return data_root() / "agents" / "owl" / "data"


# Owl Core / Mind (platform-level per-user memory)
def mind_data() -> Path:
    return data_root() / "agents" / "mind" / "data"


# High-Intent
