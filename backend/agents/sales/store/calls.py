"""Where analysed calls and the learnings taken from them are kept.

Moved out of `agents/calls/routes.py` in Stage 4, when that module was retired.
Sales-side because every consumer is now a sales agent — Call Analysis writes here,
Recap and Knowledge Capture read from it, Owl reads it to ground a conversation on a
call, and the Learn quiz aggregates over it. It sits beside `research.py` and
`prospects.py` for the same reason they do.

**The data directory did not move.** `calls_data()` still resolves under
`agents/calls/`, per the rule in `paths.py`: a package moves, a live snapshot does
not. `agents/admin` also reads `sessions.json` by direct path and is untouched.

One session file for everyone, filtered per user on read — the shape the other sales
stores use. The 200-record cap is inherited behaviour, not a new decision: it is
what has been bounding this file all along.
"""
from __future__ import annotations

from pathlib import Path

from paths import calls_data, calls_user_kb

from agents.sales.store._json import read_json, write_json

DATA_DIR = calls_data()
LEARNINGS_DIR = DATA_DIR / "learnings"
USER_KNOWLEDGE_DIR = calls_user_kb()
#: DATA_ROOT/agents/calls/knowledge — the parent of the per-user directory.
KNOWLEDGE_DIR = USER_KNOWLEDGE_DIR.parent

#: How many sessions the file keeps, across all users. Inherited from the module
#: this replaced; the call library pages from it rather than scrolling it all.
MAX_SESSIONS = 200


def _sessions_file(sandbox: bool) -> Path:
    """The live file, or the sandbox's own, so test runs never touch real calls."""
    if sandbox:
        sandboxed = DATA_DIR / "_sandbox"
        sandboxed.mkdir(parents=True, exist_ok=True)
        return sandboxed / "sessions.json"
    return DATA_DIR / "sessions.json"


def user_learnings_json(username: str, sandbox: bool = False) -> Path:
    base = DATA_DIR / "_sandbox" / "learnings" if sandbox else LEARNINGS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{username}.json"


def user_learnings_md(username: str, sandbox: bool = False) -> Path:
    """The human-readable mirror of a user's learnings, for reading in Obsidian."""
    base = KNOWLEDGE_DIR / "_sandbox" if sandbox else USER_KNOWLEDGE_DIR
    directory = base / username
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "learnings-auto.md"


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #

def load_sessions(sandbox: bool = False) -> list[dict]:
    records = read_json(_sessions_file(sandbox), [])
    return records if isinstance(records, list) else []


def save_session(session: dict, username: str, sandbox: bool = False) -> None:
    """Insert newest-first and trim to the cap. Attribution stays on the record."""
    session["username"] = username
    sessions = load_sessions(sandbox)
    sessions.insert(0, session)
    write_json(_sessions_file(sandbox), sessions[:MAX_SESSIONS])


def load_user_sessions(username: str, sandbox: bool = False) -> list[dict]:
    return [s for s in load_sessions(sandbox) if s.get("username") == username]


def get_session(call_id: str, username: str, sandbox: bool = False) -> dict | None:
    """One analysed call, or None — including when it belongs to somebody else.

    The username is part of the lookup rather than a check afterwards, so there is
    no path through this function that returns another person's call.
    """
    for session in load_sessions(sandbox):
        if session.get("id") == call_id and session.get("username") == username:
            return session
    return None


def replace_session(call_id: str, username: str, session: dict, sandbox: bool = False) -> bool:
    """Overwrite one record in place, keeping its position. False when not found.

    Used where an analysis is enriched after the fact — the product-fit pass patches
    its result rather than filing a second call.
    """
    sessions = load_sessions(sandbox)
    for index, existing in enumerate(sessions):
        if existing.get("id") == call_id and existing.get("username") == username:
            sessions[index] = {**session, "username": username}
            write_json(_sessions_file(sandbox), sessions)
            return True
    return False


def delete_session(call_id: str, username: str, sandbox: bool = False) -> bool:
    sessions = load_sessions(sandbox)
    kept = [
        s for s in sessions
        if not (s.get("id") == call_id and s.get("username") == username)
    ]
    if len(kept) == len(sessions):
        return False
    write_json(_sessions_file(sandbox), kept)
    return True


# --------------------------------------------------------------------------- #
# Learnings
# --------------------------------------------------------------------------- #

def load_learnings(username: str, sandbox: bool = False) -> list[dict]:
    records = read_json(user_learnings_json(username, sandbox), [])
    return records if isinstance(records, list) else []


def save_learnings(username: str, learnings: list[dict], sandbox: bool = False) -> None:
    write_json(user_learnings_json(username, sandbox), learnings)
