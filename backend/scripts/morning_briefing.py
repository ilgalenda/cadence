#!/usr/bin/env python3
"""Email a deterministic pipeline morning briefing — the Pipeline Manager cron entry.

Runs in-process (no HTTP, no auth), so a cron can call it directly. Loads a
user's synced deals from the Forecasting store, builds the briefing, prints it,
and emails it via the configured admin SMTP (no-ops gracefully if SMTP is unset).

Schedule it, e.g. on weekdays at 07:00:
    0 7 * * 1-5 cd /srv/cadence/backend && python scripts/morning_briefing.py --user admin
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")


def main() -> int:
    ap = argparse.ArgumentParser(description="Email a pipeline morning briefing.")
    ap.add_argument("--user", default="admin", help="username whose pipeline to summarise")
    ap.add_argument("--no-email", action="store_true", help="print the briefing only; do not send")
    args = ap.parse_args()

    # Import after load_dotenv so DATA_ROOT in .env is honoured by paths.py.
    from agents.forecast import pipeline_manager, storage
    from agents.shared.notifications import send_admin_email

    deals = storage.deals.load_user(args.user)
    today = datetime.now(timezone.utc).date()
    brief = pipeline_manager.build_briefing(deals, today)
    body = pipeline_manager.render_briefing_text(brief)
    print(body)

    if args.no_email:
        return 0
    if not deals:
        print(f"\n[briefing] no synced deals for '{args.user}' — run a forecast sync first; nothing emailed.")
        return 0
    sent = send_admin_email(f"[Cadence] Pipeline morning briefing — {brief['date']}", body)
    print(f"\n[briefing] emailed: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
