"""The one-off import of the hand-built Q4 outbound tracker.

The list existed before this package did: 40 accounts researched by hand, seeded
into a CSV, and then worked in a published web page that kept its own state. Two
sources, and **the newer one is not a superset of the older**, which is the whole
difficulty. The CSV holds the research — segment, tier, campaign, geography, roles,
confidence, value, notes — and still reads `not_started` on every row. The page
holds what has actually happened. Neither alone is the record.

**The deal composition is solved, not assumed.** The CSV carries a value but never
says what it was a price for. Searching the catalogue for combinations that hit each
figure exactly finds a *unique* answer for most of them, and those are imported as
real compositions so the tracker can reprice itself later. The rest — a figure with
no combination, or with more than one — is imported **as the figure**, flagged, and
left without a composition. Fitting an ambiguous figure to the likelier-looking
answer is precisely the silent-fallback failure the valuation module refuses to make.

**The trail starts honest.** Every imported touch and status writes an event
attributed to the person who did it with the artefact named as its source, so the
record says "this came from the page" rather than implying Cadence watched it happen.

Run once:

    DATA_ROOT=~/cadence-data python3 -m agents.outbound.importer \\
        --csv ~/path/outbound-tracker.csv --state ~/path/artifact-state.json
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
from pathlib import Path
from typing import Optional

from agents.outbound import store, valuation

#: The goals the vault records for this campaign. They are what the counters are
#: read against, and they are properties of the plan rather than of the accounts.
GOALS = {
    "goal_gbp": 100_000,
    "target_touches": 750,
    "target_replies": 35,
    "target_calls": 20,
    "target_qualified": 6,
}

#: How far the composition search will go. Two distinct shapes and ten of each
#: covers every real configuration on this list; widening it would start finding
#: coincidences rather than compositions.
MAX_SHAPES = 2
MAX_QUANTITY = 10

def solve_composition(target: int, catalogue: dict) -> Optional[dict]:
    """The one deal composition that costs exactly ``target``, or ``None``.

    ``None`` covers both "nothing adds to this" and "several things do". The caller
    treats them the same way — carry the figure, record no composition — because an
    ambiguous answer is not a weaker answer, it is a different question.
    """
    prices = {name: entry["price_gbp"] for name, entry in catalogue["shapes"].items()}
    support = catalogue.get("support", {}).get("standard_gbp_per_year", 0)
    tiers = {int(k): v for k, v in (catalogue.get("fleet_insight_annual_gbp") or {}).items()}

    found = []
    for count in range(1, MAX_SHAPES + 1):
        for shapes in itertools.combinations(sorted(prices), count):
            for quantities in itertools.product(range(1, MAX_QUANTITY + 1), repeat=count):
                base = sum(prices[s] * q for s, q in zip(shapes, quantities))
                if base > target:
                    continue
                for attach in (False, True):
                    with_support = base + (support if attach else 0)
                    for units, price in [(0, 0)] + sorted(tiers.items()):
                        if with_support + price != target:
                            continue
                        found.append({
                            "deal_lines": [
                                {"shape": s, "quantity": q} for s, q in zip(shapes, quantities)
                            ],
                            "attach_support": attach,
                            "fleet_insight_units": units,
                        })
                        if len(found) > 1:
                            return None
    return found[0] if found else None


def read_csv(path: Path) -> list[dict]:
    """The research half.

    Read with ``csv.DictReader`` rather than split on commas: one row's notes field
    is quoted and contains commas, and a naive split silently shifts every column
    after it.
    """
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def read_state(path: Path) -> dict[str, dict]:
    """The progress half, keyed by account name as the page holds it."""
    rows = json.loads(path.read_text())
    return {row["a"]: row for row in rows}


def build_proposals(csv_rows: list[dict], catalogue: Optional[dict]) -> tuple[list[dict], list[dict]]:
    """Turn the CSV into proposals, solving each value. Returns (proposals, unsolved)."""
    proposals: list[dict] = []
    unsolved: list[dict] = []

    for row in csv_rows:
        account = row["account"].strip()
        recorded = int(row["value_est_gbp"] or 0)
        composition = solve_composition(recorded, catalogue) if (catalogue and recorded) else None

        proposal = {
            "account": account,
            "segment": row["segment"].strip(),
            "tier": int(row["tier"]),
            "campaign": row["campaign"].strip(),
            "geography": row["geography"].strip(),
            "target_roles": row["target_roles"].strip(),
            "confidence": row["confidence"].strip(),
            "notes": row["notes"].strip(),
            "procurement_route": row["procurement_route"].strip(),
            "next_due": row["next_due"].strip(),
        }

        # The CSV's `trigger` column is the campaign entry condition as it was
        # researched by hand, so it is sourced to the CSV rather than to Signals.
        # An unsourced trigger is indistinguishable from an invented one.
        if row["trigger"].strip():
            proposal["trigger_text"] = row["trigger"].strip()
            proposal["trigger_source"] = "outbound-tracker.csv"

        if composition:
            proposal.update(composition)
        else:
            proposal["value_est_gbp"] = recorded
            proposal["value_note"] = (
                f"£{recorded:,} carried over from the hand-built tracker; "
                "no single composition in the catalogue accounts for it."
            )
            unsolved.append({"account": account, "value_est_gbp": recorded})

        proposals.append(proposal)

    return proposals, unsolved


def apply_state(tracker_id: str, state: dict[str, dict], actor: str) -> dict:
    """Replay the page's progress onto the record, as dated events.

    A status is set before the touches so that firing the first touch cannot drag a
    `not_started` account into `sequencing` and overwrite the status the page
    actually held.
    """
    applied = {"touches": 0, "statuses": 0}
    missing: list[str] = []

    for row in store.get_rows(tracker_id):
        page = state.get(row["account"])
        if page is None:
            missing.append(row["account"])
            continue

        if page["s"] != row["status"]:
            store.set_status(row["id"], page["s"], actor, source="artefact import")
            applied["statuses"] += 1

        for index, fired in enumerate(page["t"], start=1):
            if fired:
                store.fire_touch(row["id"], index, actor, source="artefact import")
                applied["touches"] += 1

    applied["not_on_the_page"] = missing
    return applied


def run(csv_path: Path, state_path: Path, username: str, name: str) -> dict:
    """Import the hand-built tracker. Returns what happened, including what did not."""
    catalogue = valuation.load_catalogue()
    csv_rows = read_csv(csv_path)
    state = read_state(state_path)

    proposals, unsolved = build_proposals(csv_rows, catalogue)
    tracker = store.create_tracker(name, username, **GOALS)
    added = store.add_rows(tracker["id"], proposals, actor=username)
    applied = apply_state(tracker["id"], state, actor=username)

    return {
        "tracker": tracker,
        "imported": len(added["added"]),
        "skipped": added["skipped"],
        "unsolved_values": unsolved,
        "state": applied,
        "counters": store.counters(tracker["id"]),
        "had_catalogue": catalogue is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--user", default="sam")
    parser.add_argument("--name", default="Q4 outbound")
    args = parser.parse_args()

    result = run(args.csv, args.state, args.user, args.name)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
