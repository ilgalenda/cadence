"""Where research briefs are kept.

A brief costs a web-search turn and, sometimes, Lusha credit — so it is written
down and reopened rather than re-bought, the same reasoning that makes an X-ray
shortlist worth saving.

Sales-side from the start: `lead/storage.py` and `high_intent/storage.py` are the
legacy stores the retirement slice has to relocate, and adding to them would add to
that work. This one already lives where they are going.

One file for everyone, filtered per user on read, matching how campaigns and
prospect lists are held. Attribution stays on the record; a brief belongs to the
person who asked for it.
"""
from __future__ import annotations

from pathlib import Path

from paths import sales_data

from agents.sales.store._json import new_id, now_label, read_json, write_json

DATA_DIR = sales_data()
BRIEFS_FILE = DATA_DIR / "research_briefs.json"


def _briefs_file(sandbox: bool) -> Path:
    """The live file, or the sandbox's own, so test runs never touch real briefs."""
    if sandbox:
        sandboxed = DATA_DIR / "_sandbox"
        sandboxed.mkdir(parents=True, exist_ok=True)
        return sandboxed / "research_briefs.json"
    return BRIEFS_FILE


def load_all(sandbox: bool = False) -> list[dict]:
    records = read_json(_briefs_file(sandbox), [])
    return records if isinstance(records, list) else []


def load_user_briefs(username: str, sandbox: bool = False) -> list[dict]:
    """This user's briefs, newest first."""
    mine = [r for r in load_all(sandbox) if r.get("username") == username]
    return sorted(mine, key=lambda r: r.get("updated_at") or "", reverse=True)


def get_brief(brief_id: str, username: str, sandbox: bool = False) -> dict | None:
    """One brief, or None — including when it belongs to somebody else.

    The username is part of the lookup rather than a check afterwards, so there is
    no path through this function that returns another person's brief.
    """
    for record in load_all(sandbox):
        if record.get("id") == brief_id and record.get("username") == username:
            return record
    return None


def save_brief(brief: dict, *, username: str, sandbox: bool = False) -> dict:
    """Insert or update in place, keyed on id. Returns the stored record."""
    records = load_all(sandbox)
    brief_id = brief.get("id") or new_id()
    stamp = now_label()

    record = {**brief, "id": brief_id, "username": username, "updated_at": stamp}

    for i, existing in enumerate(records):
        if existing.get("id") == brief_id and existing.get("username") == username:
            record["created_at"] = existing.get("created_at") or stamp
            records[i] = record
            break
    else:
        record["created_at"] = stamp
        records.append(record)

    write_json(_briefs_file(sandbox), records)
    return record


def delete_brief(brief_id: str, username: str, sandbox: bool = False) -> bool:
    records = load_all(sandbox)
    kept = [
        r for r in records
        if not (r.get("id") == brief_id and r.get("username") == username)
    ]
    if len(kept) == len(records):
        return False
    write_json(_briefs_file(sandbox), kept)
    return True
