"""One-shot, idempotent backfill of a user's accounts from existing stores.

Kept separate from memory.py (and using lazy imports) so the platform memory layer
never imports the agent packages at module-load time — this module is the only
place the coupling lives, and it is only touched opportunistically.

Two sources, deliberately different in kind:

  * **research briefs** — the forward source. Every brief names the account it is
    about, and Research also writes the account to memory itself, so this only
    catches briefs taken before that behaviour existed.
  * **legacy campaigns** — a frozen file. `agents/lead` was retired in Stage 3.3
    and nothing writes `campaigns.json` any more, but it still holds real company
    names for users who worked leads before the migration. It is read directly
    rather than through the deleted storage module, and this source retires with
    the file.

Vertical is left as "other" — Owl and the agents refine it later; HubSpot (Phase 4)
becomes the authoritative account/deal source and makes all of this redundant.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.mind import memory


def _accounts_from_briefs(username: str) -> list[str]:
    """Company names from this user's saved research briefs."""
    from agents.sales.store import research as briefs

    names = []
    for record in briefs.load_user_briefs(username):
        name = ((record.get("subject") or {}).get("company") or "").strip()
        if name:
            names.append(name)
    return names


def _accounts_from_legacy_campaigns(username: str) -> list[str]:
    """Company names from the retired campaign store, if the file is still there.

    Read as a plain file because the module that owned it is gone. A missing or
    unreadable file is simply no names — this is a backfill, not a migration that
    has to succeed.
    """
    from agents.sales.store._json import read_json
    from paths import sales_data

    records = read_json(sales_data() / "campaigns.json", [])
    if not isinstance(records, list):
        return []

    names = []
    for campaign in records:
        if not isinstance(campaign, dict) or campaign.get("username") != username:
            continue
        name = ((campaign.get("signal_analysis") or {}).get("company") or "").strip()
        if name:
            names.append(name)
    return names


def seed_accounts_from_existing(username: str) -> int:
    """Upsert every account this user's history names. Returns the count seeded.

    Idempotent — `upsert_account` dedupes by name — and it never raises into the
    caller: seeding is background context, and a chat turn must not fail because a
    backfill could not read a file. Each source is tried independently so one
    failing does not cost the other.
    """
    seeded = 0
    seen: set[str] = set()

    for source, collect in (
        ("seed:research", _accounts_from_briefs),
        ("seed:lead", _accounts_from_legacy_campaigns),
    ):
        try:
            names = collect(username)
        except Exception:
            continue

        for name in names:
            # Checked here as well as in each collector: a nameless account is
            # useless and unremovable through the UI, so the last gate before the
            # write refuses it rather than trusting every caller to have.
            name = (name or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            try:
                memory.upsert_account(username, name, source=source)
                seeded += 1
            except Exception:
                pass

    return seeded


# Records that the backfill has been attempted for a user. A preference rather
# than a file of its own: it is per-user state about the user, which is what the
# preference store is.
SEEDED_KEY = "accounts_seeded_at"


def seed_if_empty(username: str) -> None:
    """Seed once per user, and remember that it happened.

    The guard used to be "this user has no accounts yet", which never flips for
    a user whose history names none — so every chat turn re-read every research
    brief and the whole legacy campaign file, synchronously, on the request path.

    The marker records the **attempt**, not the outcome, which is what makes it
    one-time: a user with nothing to seed is done after the first turn, the same
    as a user with plenty. Still swallowing failures — seeding is background
    context and must never cost a chat turn.
    """
    try:
        if memory.get_preferences(username).get(SEEDED_KEY):
            return
        if not memory.list_accounts(username, status=None):
            seed_accounts_from_existing(username)
        memory.remember_preference(username, SEEDED_KEY, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass
