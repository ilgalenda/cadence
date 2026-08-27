"""The watchlist, and what has already been seen on it.

Signals watches named accounts for events — funding rounds, timing technographics.
Two things are stored per account: that it is watched, and **the fingerprints of
every finding already reported**.

**That second half is the whole difference between a monitor and a repeated search.**
A funding round found on Monday must not be reported again on Tuesday; without a
`seen` set, "what's new" would return the same five items every sweep and the feature
would be a search box with extra steps.

**On the `paths.py` forward reference.** `sales_signals_data()` carries the note
*"Always sandboxed; see `agents.sales.store.signals` for why that rule is
preserved."* This module is that forward reference, and the reasoning did not survive
— the module was never written, and the live directory holds only `_sandbox`. Rather
than inherit a rule whose justification cannot be checked, the watchlist follows the
same live/sandbox convention as every other sales store: a `sandbox` flag per call,
`_sandbox` only when the request is one. A watchlist Sam curates is his real data.
The directory itself keeps its `high_intent` name for the reason `paths.py` gives:
a package moves, a snapshot does not.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from paths import sales_signals_data

from agents.sales.store._json import new_id, now_label, read_json, write_json

DATA_DIR = sales_signals_data()
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

#: How many accounts one person may watch. A watchlist multiplies every per-account
#: cost of a sweep, so the ceiling is a spend guard, not a storage one.
MAX_WATCHED = 50

#: Fingerprints kept per account, oldest dropped first. Unbounded, a long-watched
#: account would grow this file forever; at this size an event would have to be
#: re-found 200 findings later to be reported twice, which is not a real case.
MAX_SEEN = 200

#: Findings kept per account, newest first. The fingerprints alone would make the
#: monitor correct but useless: a sweep in a background thread would report to
#: nobody, and the page would only ever show what the sweep it happened to trigger
#: found. Keeping the findings is what lets a surface — and GTM's digest — read what
#: is new without spending a search.
MAX_RECENT = 20

#: How long an account's last check stays fresh. A day: funding rounds and
#: technographic changes are not hourly news, and every check costs a web-search turn.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _watchlist_file(sandbox: bool) -> Path:
    if sandbox:
        sandboxed = DATA_DIR / "_sandbox"
        sandboxed.mkdir(parents=True, exist_ok=True)
        return sandboxed / "watchlist.json"
    return WATCHLIST_FILE


def _load_all(sandbox: bool) -> list[dict]:
    records = read_json(_watchlist_file(sandbox), [])
    return records if isinstance(records, list) else []


def _save_all(records: list[dict], sandbox: bool) -> None:
    write_json(_watchlist_file(sandbox), records)


# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #

def fingerprint(finding: dict) -> str:
    """A stable identity for one finding.

    **The source URL wins when there is one.** A headline drifts — an article gets
    re-titled, a model paraphrases it differently on the next sweep — but the URL it
    was found at does not. Falling back to a hash of kind + headline covers findings
    that arrive without one, though those are dropped by the agent anyway.

    Normalised before hashing so trailing slashes, case and query strings do not
    make one event look like two.
    """
    url = str(finding.get("url") or "").strip().lower()
    if url:
        url = url.split("?", 1)[0].rstrip("/")
        # Scheme and www are noise for identity; the same page under http and https
        # is the same page.
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
        if url.startswith("www."):
            url = url[4:]
        return "u:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    kind = str(finding.get("kind") or "").strip().lower()
    headline = " ".join(str(finding.get("headline") or "").strip().lower().split())
    if not headline:
        return ""
    return "h:" + hashlib.sha256(f"{kind}|{headline}".encode("utf-8")).hexdigest()[:16]


def is_new(finding: dict, seen: set[str] | list[str]) -> bool:
    """Whether this finding has not been reported before.

    A finding with no usable fingerprint is treated as **not** new — it cannot be
    remembered, so reporting it would mean reporting it on every sweep forever.
    """
    mark = fingerprint(finding)
    return bool(mark) and mark not in set(seen)


# --------------------------------------------------------------------------- #
# The watchlist
# --------------------------------------------------------------------------- #

def watchlist(username: str, sandbox: bool = False) -> list[dict]:
    """This user's watched accounts, most recently added first."""
    mine = [r for r in _load_all(sandbox) if r.get("username") == username]
    return sorted(mine, key=lambda r: r.get("added_at") or "", reverse=True)


def get_watched(entry_id: str, username: str, sandbox: bool = False) -> dict | None:
    """One watched account, or None — including when it is somebody else's.

    The username is part of the lookup rather than a check afterwards, so no path
    through this function returns another person's watchlist entry.
    """
    for record in _load_all(sandbox):
        if record.get("id") == entry_id and record.get("username") == username:
            return record
    return None


def watch(username: str, company: str, sandbox: bool = False) -> dict:
    """Start watching an account. Watching one already watched returns it unchanged.

    Idempotent on the company name, case-insensitively: pressing the button twice
    should not produce two entries that then cost two web-search turns per sweep.
    """
    company = (company or "").strip()
    if not company:
        raise ValueError("Name the account to watch.")

    records = _load_all(sandbox)
    for record in records:
        if record.get("username") == username and \
                (record.get("company") or "").strip().lower() == company.lower():
            return record

    mine = [r for r in records if r.get("username") == username]
    if len(mine) >= MAX_WATCHED:
        raise ValueError(
            f"You are watching {MAX_WATCHED} accounts already — every sweep costs a "
            "search per account. Remove one first."
        )

    entry = {
        "id": new_id(),
        "username": username,
        "company": company,
        "added_at": now_label(),
        # Never checked. Deliberately not "now": a new account should be swept on the
        # next opportunity, not a day later.
        "last_checked_at": "",
        "last_checked_ts": 0,
        "seen": [],
    }
    records.insert(0, entry)
    _save_all(records, sandbox)
    return entry


def unwatch(entry_id: str, username: str, sandbox: bool = False) -> bool:
    records = _load_all(sandbox)
    kept = [
        r for r in records
        if not (r.get("id") == entry_id and r.get("username") == username)
    ]
    if len(kept) == len(records):
        return False
    _save_all(kept, sandbox)
    return True


def record_check(
    entry_id: str,
    username: str,
    *,
    fingerprints: list[str] | None = None,
    findings: list[dict] | None = None,
    sandbox: bool = False,
) -> dict | None:
    """Stamp an account as checked, remember what was found, and keep the findings.

    Called even when a check found nothing, and even when it **failed** — otherwise a
    company whose page reliably errors would be retried on every sweep forever,
    spending a turn each time. The stamp is "we looked", not "we succeeded".

    Both halves matter: `seen` is what stops a finding being reported twice, and
    `recent` is what lets a surface show it at all. A sweep runs in a background
    thread with no caller waiting, so a finding it does not store is a finding
    reported to nobody.
    """
    records = _load_all(sandbox)
    for record in records:
        if record.get("id") != entry_id or record.get("username") != username:
            continue

        seen = [f for f in (record.get("seen") or []) if isinstance(f, str)]
        for mark in fingerprints or []:
            if mark and mark not in seen:
                seen.append(mark)

        stamped = now_label()
        fresh = [
            {**f, "found_at": stamped}
            for f in (findings or []) if isinstance(f, dict)
        ]
        previous = [f for f in (record.get("recent") or []) if isinstance(f, dict)]

        record["seen"] = seen[-MAX_SEEN:]
        # Newest first, so a surface reads the top of the list and a cap drops the
        # oldest rather than the news.
        record["recent"] = (fresh + previous)[:MAX_RECENT]
        record["last_checked_at"] = stamped
        record["last_checked_ts"] = int(time.time())
        _save_all(records, sandbox)
        return record
    return None


def stale(entry: dict, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    """Whether this account is due a check.

    Per account, not per watchlist: adding one company should cost one search, not a
    full re-sweep of everything already fresh.
    """
    try:
        checked = int(entry.get("last_checked_ts") or 0)
    except (TypeError, ValueError):
        return True
    # `>=`, so a caller passing ttl_seconds=0 gets "everything is due" — which is
    # plainly what zero means — rather than "nothing is, for one more second".
    return (int(time.time()) - checked) >= ttl_seconds


def due(username: str, ttl_seconds: int = DEFAULT_TTL_SECONDS, sandbox: bool = False) -> list[dict]:
    """The watched accounts needing a check, oldest first — so a truncated sweep
    does the most overdue work rather than a random slice."""
    entries = [e for e in watchlist(username, sandbox) if stale(e, ttl_seconds)]
    return sorted(entries, key=lambda e: int(e.get("last_checked_ts") or 0))
