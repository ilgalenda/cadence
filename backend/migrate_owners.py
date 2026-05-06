"""One-shot backfill: stamp existing user-owned records with username='ivan'.

Idempotent. Run from the backend/ directory:

    python3 migrate_owners.py
"""
import json
from pathlib import Path

DEFAULT_OWNER = "ivan"

TARGETS = [
    Path(__file__).parent / "agents" / "calls" / "data" / "sessions.json",
    Path(__file__).parent / "agents" / "lead" / "data" / "campaigns.json",
    Path(__file__).parent / "agents" / "lead" / "data" / "leads.json",
]


def migrate(path: Path) -> int:
    if not path.exists():
        print(f"skip (missing): {path}")
        return 0
    try:
        records = json.loads(path.read_text())
    except Exception as e:
        print(f"skip (unreadable): {path} — {e}")
        return 0
    if not isinstance(records, list):
        print(f"skip (not a list): {path}")
        return 0
    changed = 0
    for r in records:
        if isinstance(r, dict) and not r.get("username"):
            r["username"] = DEFAULT_OWNER
            changed += 1
    if changed:
        path.write_text(json.dumps(records, indent=2))
    print(f"{path.name}: stamped {changed} record(s)")
    return changed


def main() -> int:
    total = sum(migrate(p) for p in TARGETS)
    print(f"\ntotal: {total} record(s) updated to username='{DEFAULT_OWNER}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
