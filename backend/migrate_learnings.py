"""One-shot migration: split shared learnings into per-user files.

Before: backend/agents/{calls,lead}/data/learnings.json and
        backend/agents/{calls,lead}/knowledge/learnings-auto.md were single
        shared files used by every authenticated user.

After:  backend/agents/{calls,lead}/data/learnings/{username}.json and
        backend/agents/{calls,lead}/knowledge/_user/{username}/learnings-auto.md
        per the per-user isolation refactor.

Run from the backend/ directory:

    python migrate_learnings.py

The original files are renamed to *.bak so re-running is a no-op.
Rows whose source_call_id / source_campaign_id can't be attributed to a user
fall back to FALLBACK_USER (the historical sole user — ivan).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
FALLBACK_USER = "ivan"

CALLS_DIR = BACKEND_DIR / "agents" / "calls"
LEAD_DIR = BACKEND_DIR / "agents" / "lead"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _attribute_calls() -> int:
    """Split calls/data/learnings.json + calls/knowledge/learnings-auto.md."""
    json_src = CALLS_DIR / "data" / "learnings.json"
    md_src = CALLS_DIR / "knowledge" / "learnings-auto.md"
    out_json_dir = CALLS_DIR / "data" / "learnings"
    out_md_root = CALLS_DIR / "knowledge" / "_user"

    if not json_src.exists() and not md_src.exists():
        print("[calls] nothing to migrate")
        return 0

    sessions = _read_json(CALLS_DIR / "data" / "sessions.json", [])
    call_owner = {
        s.get("id"): s.get("username") for s in sessions if s.get("id") and s.get("username")
    }

    rows = _read_json(json_src, [])
    by_user: dict[str, list[dict]] = {}
    for row in rows:
        owner = call_owner.get(row.get("source_call_id")) or FALLBACK_USER
        by_user.setdefault(owner, []).append(row)

    out_json_dir.mkdir(parents=True, exist_ok=True)
    for username, user_rows in by_user.items():
        target = out_json_dir / f"{username}.json"
        existing = _read_json(target, [])
        # Newest-first ordering preserved by prepending fresh rows.
        _atomic_write_json(target, user_rows + existing)

    # Markdown: every historical block is attributed to FALLBACK_USER (we can't
    # cleanly split the markdown by source_call_id without re-parsing). The
    # JSON split above is what actually feeds future loads via the per-user dirs.
    if md_src.exists():
        md_target_dir = out_md_root / FALLBACK_USER
        md_target_dir.mkdir(parents=True, exist_ok=True)
        md_target = md_target_dir / "learnings-auto.md"
        existing_md = md_target.read_text(encoding="utf-8") if md_target.exists() else ""
        md_target.write_text(md_src.read_text(encoding="utf-8") + existing_md, encoding="utf-8")

    if json_src.exists():
        json_src.rename(json_src.with_suffix(".json.bak"))
    if md_src.exists():
        md_src.rename(md_src.with_suffix(".md.bak"))

    print(f"[calls] migrated {len(rows)} learning rows across {len(by_user)} user(s)")
    return len(rows)


def _attribute_lead() -> int:
    """Split lead/data/learnings.json + lead/knowledge/learnings-auto.md."""
    json_src = LEAD_DIR / "data" / "learnings.json"
    md_src = LEAD_DIR / "knowledge" / "learnings-auto.md"
    out_json_dir = LEAD_DIR / "data" / "learnings"
    out_md_root = LEAD_DIR / "knowledge" / "_user"

    if not json_src.exists() and not md_src.exists():
        print("[lead] nothing to migrate")
        return 0

    campaigns = _read_json(LEAD_DIR / "data" / "campaigns.json", [])
    campaign_owner = {
        c.get("id"): c.get("username") for c in campaigns if c.get("id") and c.get("username")
    }

    rows = _read_json(json_src, [])
    by_user: dict[str, list[dict]] = {}
    for row in rows:
        owner = campaign_owner.get(row.get("source_campaign_id")) or FALLBACK_USER
        by_user.setdefault(owner, []).append(row)

    out_json_dir.mkdir(parents=True, exist_ok=True)
    for username, user_rows in by_user.items():
        target = out_json_dir / f"{username}.json"
        existing = _read_json(target, [])
        _atomic_write_json(target, user_rows + existing)

    if md_src.exists():
        md_target_dir = out_md_root / FALLBACK_USER
        md_target_dir.mkdir(parents=True, exist_ok=True)
        md_target = md_target_dir / "learnings-auto.md"
        existing_md = md_target.read_text(encoding="utf-8") if md_target.exists() else ""
        md_target.write_text(md_src.read_text(encoding="utf-8") + existing_md, encoding="utf-8")

    if json_src.exists():
        json_src.rename(json_src.with_suffix(".json.bak"))
    if md_src.exists():
        md_src.rename(md_src.with_suffix(".md.bak"))

    print(f"[lead] migrated {len(rows)} learning rows across {len(by_user)} user(s)")
    return len(rows)


def main() -> int:
    total = _attribute_calls() + _attribute_lead()
    print(f"done — {total} rows migrated. Originals preserved as *.bak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
