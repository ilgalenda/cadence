#!/usr/bin/env python3
"""Stand up a throwaway instance with invented data, for the screenshots.

The three app images in `docs/images/` show the running platform. They must not
show the platform *running on real data* — the live event calendar holds the
shows a real company is exhibiting at and the colleagues going to them, which is
commercial intelligence and personal data in one table.

So this seeds a `DATA_ROOT` that exists only to be photographed and thrown away.
Everything in it is invented, in the same register as the rest of the public
build: `Northgate`, `Meridian`, `Sam Whitfield`. Nothing is read from anywhere.

    DATA_ROOT=/tmp/cadence-demo tools/seed-demo.py

Then run the backend against the same `DATA_ROOT` and shoot with
`tools/shoot-screenshots.mjs app`.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

DEMO_USER = "demo"

#: Four shows across one year, none of them real, spaced so the calendar has a
#: past, a present and a horizon rather than one cluster.
SHOWS = [
    ("Northgate Expo", "Amsterdam", "Netherlands", 34, "approved", True, 14_000),
    ("Meridian Summit", "London", "United Kingdom", 63, "approved", False, None),
    ("Open Rack Forum", "San Jose", "United States", 96, "proposed", True, 12_500),
    ("Vantage Timing Forum", "Geneva", "Switzerland", 145, "proposed", False, None),
]


def seed_users(root: Path) -> None:
    """One admin, so a screenshot can sign in. Password is not a secret here."""
    import bcrypt  # noqa: PLC0415 — only needed when actually seeding

    agents = root / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    # Both files are wrapped — `auth.load_users` reads `users`, and
    # `_load_credentials` reads `credentials`. A bare list parses and then finds
    # nobody, which surfaces as a 500 on sign-in rather than as a bad file.
    (agents / "users.json").write_text(json.dumps({"users": [{
        "username": DEMO_USER,
        "name": "Sam Whitfield",
        "role": "Head of Go-To-Market",
        "access": "admin",
        "agents": ["lead", "calls"],
    }]}, indent=2), encoding="utf-8")
    (agents / "users_credentials.json").write_text(json.dumps({"credentials": {
        DEMO_USER: bcrypt.hashpw(b"demo", bcrypt.gensalt()).decode(),
    }}, indent=2), encoding="utf-8")
    print(f"   seeded  1 user ({DEMO_USER} / demo)")


def seed_events() -> None:
    from agents.events import db, store  # noqa: PLC0415

    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()

    today = date.today()
    for name, city, country, offset, status, exhibiting, cost in SHOWS:
        starts = today + timedelta(days=offset)
        event = store.register_interest(DEMO_USER, {
            "name": name,
            "location": city,
            "country": country,
            "starts_on": starts.isoformat(),
            "ends_on": (starts + timedelta(days=3)).isoformat(),
            "invited": True,
            "intent": "exhibiting" if exhibiting else "attending",
            "exhibiting": exhibiting,
            "exhibit_cost": cost,
            "exhibit_currency": "GBP",
            # The store insists on these when exhibiting, and it is right to:
            # a stand cost with nobody to chase it is not a quote.
            "quote_contact_name": "Stand sales",
            "quote_contact_email": "stands@acme.example",
            "demo_required": exhibiting,
            "demo_type": "Timing rack, two nodes" if exhibiting else "",
            "submission_deadline": (starts - timedelta(days=60)).isoformat() if exhibiting else "",
            "needs_travel": True,
            "travel_legs": [{"mode": "flight", "from": "London", "to": city, "nights": 3}],
            "needs_material": exhibiting,
            "material_items": ["cards", "clothing"] if exhibiting else [],
            "ticket_cost": 0,
            "rationale": "Our buyers are in the room, and two competitors exhibit.",
            "decide_by": (starts - timedelta(days=45)).isoformat(),
        })
        if status == "approved":
            store.decide_event(event["id"], status="approved", admin=DEMO_USER,
                               note="Worth the stand.")
    print(f"   seeded  {len(SHOWS)} shows")


def seed_tracker() -> None:
    from agents.outbound import db, store  # noqa: PLC0415
    from paths import outbound_pricing_file  # noqa: PLC0415

    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()

    # Give the demo the example catalogue, so the tracker prices its rows instead
    # of showing three "unpriced". An absent catalogue is a supported state and
    # worth demonstrating — but not in the one picture of the feature working.
    catalogue = outbound_pricing_file()
    catalogue.parent.mkdir(parents=True, exist_ok=True)
    catalogue.write_text(
        (Path(__file__).resolve().parent.parent / "backend" / "agents" / "outbound"
         / "pricing.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"   seeded  the example price catalogue")
    tracker = store.create_tracker("Q1 outbound", DEMO_USER, goal_gbp=100_000,
                                   target_touches=200, target_replies=10,
                                   target_calls=5, target_qualified=2)
    store.add_rows(tracker["id"], [
        {"account": "Northgate Nordics", "segment": "Neutral host", "tier": 1,
         "campaign": "B-tdd", "geography": "Nordics", "confidence": "high",
         "deal_lines": [{"shape": "primary_quorum", "quantity": 1}],
         "attach_support": True},
        {"account": "Meridian Towers", "segment": "Neutral host", "tier": 2,
         "campaign": "B-tdd", "geography": "Iberia", "confidence": "medium",
         "deal_lines": [{"shape": "brownfield_backup", "quantity": 1}],
         "attach_support": False},
        {"account": "Corvus Radio", "segment": "Equipment", "tier": 3,
         "campaign": "A-jamming", "geography": "Ireland", "confidence": "low",
         "deal_lines": [], "attach_support": False},
    ], actor=DEMO_USER)
    print("   seeded  1 tracker, 3 accounts")


def main() -> int:
    root = Path(os.environ.get("DATA_ROOT", "")).expanduser()
    if not root or root == Path.home() / "cadence-data":
        raise SystemExit(
            "Set DATA_ROOT to a throwaway directory first.\n"
            "This must never run against a real instance."
        )
    root.mkdir(parents=True, exist_ok=True)
    print(f"seeding {root}")
    seed_users(root)
    seed_events()
    seed_tracker()
    print("\nDone. Run the backend against the same DATA_ROOT, then:")
    print("   tools/shoot-screenshots.mjs app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
