#!/usr/bin/env python3
"""Import a colleague's knowledge file into the Cadence vault's review queue.

    python3 import_contributions.py contributions.json --as jakub                    # check only
    python3 import_contributions.py contributions.json --as jakub --write            # queue for review
    python3 import_contributions.py contributions.json --as jakub --approve-as sam  # queue and approve

Reads the JSON produced from `contributions.template.json`, validates it, and
writes each entry into `vault/added/pending/`. Nothing reaches Owl here: pending
entries are never loaded, and an admin approves them in the existing Added queue
(the dashboard's `pending_added_count`, `/api/admin/added/pending`).

**Checking is the default and writing is opt-in.** The alternative — write first,
report afterwards — leaves a partial batch in the vault when entry ninety of two
hundred turns out to be malformed, and there is no un-import.

**A batch with problems does not write at all** unless `--force`. One bad record
usually means the export went wrong rather than that one fact is wrong, and the
cheap fix is to send it back rather than to half-import it. `--force` writes the
entries that passed and skips the rest, which is the right call once you have
read the problems and decided.

**`--as` is the contributor, and it must be a real Cadence username.** The JSON's
`contributed_by` is a display name; this is the identity the vault records, and
it is what makes an entry show up as *theirs* in their own Owl and wiki (see
`agents/mind/contributions_block.py`). A name nobody can log in as gives them
knowledge they can never be shown as owning, so it is checked against the user
registry rather than trusted.

**`--approve-as <admin>` publishes in the same pass**, reusing `vault.approve_added`
and implying `--write`. Without it the entries sit in the pending queue as before.

**The contributor and the approver are two different people, and the flags keep
them apart.** The usual case is an admin importing a colleague's exported
knowledge: `--as jakub --approve-as sam` records Jakub as the author — which is
what makes it show up as *his* work in *his* Owl — while Sam is recorded as the
reviewer. Collapsing them into one flag silently attributed every import to
whoever ran it, and the contributor never saw their own work.

Approving does not change who can read what: the vault is global, and an approved
entry is in every user's context. What attribution changes is presentation — the
contributor sees their own work named as theirs.

Every entry in one run shares a `batch_id`, so a bad import can be found and
reversed as a unit:

    grep -rl "batch_id: <id>" ~/cadence-data/vault/added/{pending,approved}/
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

import auth  # noqa: E402
from agents.shared import contributions  # noqa: E402
from agents.shared import vault  # noqa: E402


def _find(username: str) -> tuple[dict | None, str]:
    user = auth.find_user(username)
    if user is not None:
        return user, ""
    known = ", ".join(sorted(u.get("username", "") for u in auth.load_users()))
    return None, f"No Cadence user named {username!r}. Known users: {known}"


def resolve_contributor(username: str) -> tuple[dict | None, str]:
    """The user record to attribute the knowledge to, or (None, why not).

    Checked against the registry rather than trusted: attribution that does not
    resolve to an account somebody can sign into is attribution nobody will ever
    be shown, which quietly defeats the point of recording it.
    """
    user, problem = _find(username)
    if user is None:
        return None, problem
    if not user.get("password_hash"):
        return None, (
            f"{username!r} has a profile but no credentials, so they cannot sign in — "
            "their contributions would be attributed to an account nobody can reach. "
            "Give them a login first."
        )
    return user, ""


def resolve_approver(username: str) -> tuple[dict | None, str]:
    """The admin recorded as having reviewed the batch, or (None, why not)."""
    user, problem = _find(username)
    if user is None:
        return None, problem
    if user.get("access") != "admin":
        return None, f"--approve-as needs an admin; {username!r} has access={user.get('access')!r}"
    return user, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path, help="the contributions JSON file")
    parser.add_argument("--as", dest="owner", required=True,
                        help="the contributing Cadence username (attribution, not a display name)")
    parser.add_argument("--write", action="store_true", help="commit to the pending queue")
    parser.add_argument("--approve-as", dest="approver", default="",
                        help="admin username to approve the batch as; implies --write")
    parser.add_argument("--force", action="store_true", help="write the valid entries despite problems")
    args = parser.parse_args()

    owner, why_not = resolve_contributor(args.owner)
    if owner is None:
        print(why_not)
        return 2

    approver = None
    if args.approver:
        approver, why_not = resolve_approver(args.approver)
        if approver is None:
            print(why_not)
            return 2
        args.write = True

    try:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"No such file: {args.file}")
        return 2
    except json.JSONDecodeError as e:
        print(f"{args.file} is not valid JSON: {e}")
        print("A trailing comma or an unescaped quote is the usual cause.")
        return 2

    entries, problems = contributions.validate_batch(payload)
    # The template ships a placeholder; a contributor who never replaced it must
    # not have "REPLACE WITH YOUR NAME" quoted at colleagues inside Owl's prompt.
    claimed = str(payload.get("contributed_by") or "").strip()
    display_name = (
        owner.get("name") or args.owner
        if not claimed or claimed.upper() == "REPLACE WITH YOUR NAME"
        else claimed
    )

    print(f"\n{args.file.name} — {len(entries)} usable, {len(problems)} problem(s)")
    print(f"attributed to: {args.owner} ({display_name})")
    if approver is not None:
        print(f"approved by:   {args.approver}")

    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  · {problem}")

    if entries:
        by_kind: dict[str, int] = {}
        for entry in entries:
            by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
        print("\nUsable entries by kind:")
        for kind, n in sorted(by_kind.items()):
            print(f"  {n:4d}  {kind}")

    if not entries:
        print("\nNothing to import.")
        return 1

    if not args.write:
        print("\nChecked only. Re-run with --write to add these to the pending queue.")
        return 0 if not problems else 1

    if problems and not args.force:
        print(
            "\nNot written. Fix the problems above and re-run, or pass --force to "
            "write the usable entries and skip the rest."
        )
        return 1

    batch_id = uuid.uuid4().hex[:12]
    written = 0
    approved = 0
    for entry in entries:
        try:
            path = vault.write_contribution(
                title=entry["title"],
                description=entry["description"],
                content=entry["content"],
                kind=entry["kind"],
                entity_type=entry["entity_type"],
                aliases=entry["aliases"],
                tags=entry["tags"],
                products=entry["products"],
                source=entry["source"],
                confidence=entry["confidence"],
                contributed_by=args.owner,
                display_name=display_name,
                batch_id=batch_id,
            )
            written += 1
            if approver is not None:
                entry_id = path.name.split("--", 1)[0]
                vault.approve_added(entry_id, reviewed_by=args.approver,
                                    review_notes=f"approved on import, batch {batch_id}")
                approved += 1
        except Exception as e:  # noqa: BLE001 — one bad write must not lose the rest
            print(f"  ! {entry['title'][:60]!r} did not write: {e}")

    print(f"\nWrote {written} entr{'y' if written == 1 else 'ies'}, attributed to {args.owner}.")
    print(f"batch_id: {batch_id}")
    if approver is not None:
        print(f"Approved {approved} of them — live in every user's Owl context from the next turn.")
        print(f"{display_name} will also see them named as their own work.")
    else:
        print("Nothing is visible to Owl until you approve it in the admin Added queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
