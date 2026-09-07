"""Where X-ray's shortlists are kept.

Moved out of `agents/lead/storage.py` in R4. It sat there because the retired
`lead/prospect.astro` was the first surface to save one, but shortlists are X-ray's
and this is where its research briefs already live — so the new code no longer
reaches into a package that is being retired.

**The file path is deliberately unchanged.** Renaming the module is a code change;
moving the data is not, and a live snapshot should never be rewritten to match a
package name. Anything saved before this move opens exactly as it did — including
the emails and phone numbers already paid for, which is the whole reason a
shortlist is worth saving.
"""
from __future__ import annotations

from pathlib import Path

from paths import sales_data

from agents.sales.store._json import new_id, now_label, read_json, write_json

DATA_DIR = sales_data()
PROSPECTS_FILE = DATA_DIR / "prospects.json"

#: Shortlists kept per install, newest first. Bounded so the file cannot grow
#: without limit; nothing depends on an old one still being there.
PROSPECT_CAP = 200


def _prospects_file(sandbox: bool) -> Path:
    """The live file, or the sandbox's own."""
    if sandbox:
        sandboxed = DATA_DIR / "_sandbox"
        sandboxed.mkdir(parents=True, exist_ok=True)
        return sandboxed / "prospects.json"
    return PROSPECTS_FILE


def new_prospect_id() -> str:
    """Named for what it identifies; the id itself is the shared one."""
    return new_id()


def load_prospect_lists(sandbox: bool = False) -> list[dict]:
    return read_json(_prospects_file(sandbox), [])


def load_user_prospect_lists(username: str, sandbox: bool = False) -> list[dict]:
    return [p for p in load_prospect_lists(sandbox) if p.get("username") == username]


def get_prospect_list(
    prospect_id: str, username: str | None = None, sandbox: bool = False,
) -> dict | None:
    """One shortlist, or None — including when it belongs to somebody else."""
    for record in load_prospect_lists(sandbox):
        if record.get("id") != prospect_id:
            continue
        if username is not None and record.get("username") != username:
            return None
        return record
    return None


def save_prospect_list(
    record: dict, username: str | None = None, sandbox: bool = False,
) -> dict | None:
    """Insert or update a shortlist by id, or None when it is someone else's.

    Newest first, capped.

    **The id decides which record is replaced, and the id comes from the client**
    — `ShortlistSave` accepts one, which the model it replaced did not. So the
    owner has to be checked here: replacing purely on a matching id let anyone
    who knew an id destroy that shortlist, including the emails and phone numbers
    Lusha had already been paid for. `get_prospect_list` and
    `delete_prospect_list` both check the owner; this was the write path that did
    not.

    Refusing rather than inserting matters too: dropping the ownership check from
    the delete but keeping the insert would leave two records sharing one id, and
    every later read would pick whichever came first.
    """
    if not record.get("id"):
        record["id"] = new_prospect_id()
    if not record.get("created_at"):
        record["created_at"] = now_label()
    record["updated_at"] = now_label()
    if username is not None:
        record["username"] = username

    lists = load_prospect_lists(sandbox)
    if username is not None and any(
        p.get("id") == record["id"] and p.get("username") != username for p in lists
    ):
        return None

    kept = [p for p in lists if p.get("id") != record["id"]]
    kept.insert(0, record)
    write_json(_prospects_file(sandbox), kept[:PROSPECT_CAP])
    return record


def delete_prospect_list(
    prospect_id: str, username: str | None = None, sandbox: bool = False,
) -> bool:
    lists = load_prospect_lists(sandbox)
    kept = [
        p for p in lists
        if not (p.get("id") == prospect_id
                and (username is None or p.get("username") == username))
    ]
    if len(kept) == len(lists):
        return False
    write_json(_prospects_file(sandbox), kept)
    return True
