"""Phase 0 — One-time migration of all existing Cadence data into the vault.

Migrates:
  - Curated knowledge KB files → vault/knowledge/
  - All users' call learnings (JSON) → vault/calls/
  - All users' campaign learnings (JSON) → vault/lead/
  - sessions.json knowledge_extracts → vault/calls/ (type: session_extract)

Safe to run multiple times — skips files that already exist by ID.
Does NOT delete original files.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so imports work
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from agents.shared.vault import (
    CALLS_DIR,
    GLOSSARY_DIR,
    KNOWLEDGE_DIR,
    LEAD_DIR,
    VAULT_DIR,
    _slug,
    _write_fm,
    write_learning,
)

CALLS_AGENT_DIR = BACKEND_DIR / "agents" / "calls"
LEAD_AGENT_DIR = BACKEND_DIR / "agents" / "lead"

CALLS_KNOWLEDGE_DIR = CALLS_AGENT_DIR / "knowledge"
CALLS_LEARNINGS_DIR = CALLS_AGENT_DIR / "data" / "learnings"
CALLS_SESSIONS_FILE = CALLS_AGENT_DIR / "data" / "sessions.json"
LEAD_LEARNINGS_DIR = LEAD_AGENT_DIR / "data" / "learnings"


def _existing_ids(directory: Path) -> set[str]:
    """Collect all IDs already in the vault directory (from frontmatter)."""
    ids = set()
    for path in directory.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    for line in text[3:end].split("\n"):
                        if line.startswith("id: "):
                            ids.add(line[4:].strip())
        except Exception:
            pass
    return ids


def migrate_knowledge_files() -> int:
    """Copy shared KB .md files into vault/knowledge/ verbatim."""
    copied = 0
    for path in CALLS_KNOWLEDGE_DIR.glob("*.md"):
        if path.parent.name == "_user":
            continue
        dest = KNOWLEDGE_DIR / path.name
        if dest.exists():
            print(f"  [skip] knowledge/{path.name} already in vault")
            continue
        shutil.copy2(path, dest)
        print(f"  [ok]   knowledge/{path.name}")
        copied += 1
    return copied


def migrate_learnings_json(
    learnings_dir: Path,
    agent: str,
    existing_ids: set[str],
) -> int:
    """Migrate all {username}.json files from a learnings directory."""
    written = 0
    if not learnings_dir.exists():
        return 0
    for json_path in learnings_dir.glob("*.json"):
        username = json_path.stem
        try:
            entries = json.loads(json_path.read_text())
        except Exception as e:
            print(f"  [err]  {json_path.name}: {e}")
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            entry_id = entry.get("id", "")
            if entry_id in existing_ids:
                continue
            title = str(entry.get("title", "")).strip()
            content = str(entry.get("content", "")).strip()
            category = str(entry.get("category", "general")).strip()
            if not title or not content:
                continue

            # Build source reference depending on agent type
            if agent == "calls":
                source_id = entry.get("source_call_id", "")
                source_title = entry.get("source_call_title", "")
            else:
                source_id = entry.get("source_campaign_id", "")
                source_title = entry.get("source_campaign_title", "")

            target_dir = CALLS_DIR if agent == "calls" else LEAD_DIR
            slug = _slug(title)
            filename = f"{entry_id[:8]}--{slug}.md" if len(entry_id) >= 8 else f"migr--{slug}.md"
            meta = {
                "id": entry_id,
                "title": title,
                "type": "learning",
                "category": category,
                "agent": agent,
                "contributed_by": username,
                "source_id": source_id,
                "source_title": source_title,
                "tags": [],
                "products": [],
                "created_at": entry.get("created_at", ""),
            }
            path = target_dir / filename
            path.write_text(_write_fm(meta) + "\n\n" + content, encoding="utf-8")
            existing_ids.add(entry_id)
            print(f"  [ok]   {agent}/{filename}")
            written += 1
    return written


def migrate_session_extracts(existing_ids: set[str]) -> int:
    """Migrate knowledge_extracts from sessions.json into vault/calls/."""
    if not CALLS_SESSIONS_FILE.exists():
        return 0
    try:
        sessions = json.loads(CALLS_SESSIONS_FILE.read_text())
    except Exception as e:
        print(f"  [err]  sessions.json: {e}")
        return 0

    written = 0
    for session in sessions:
        if session.get("type") != "call_analysis":
            continue
        session_id = session.get("id", "")
        session_title = session.get("title", "Call Analysis")
        username = session.get("username", "unknown")
        result = session.get("result") or {}
        extracts = result.get("knowledge_extracts") or []
        if not extracts:
            continue
        for extract in extracts:
            if not isinstance(extract, dict):
                continue
            title = str(extract.get("title", "")).strip()
            content = str(extract.get("content", "")).strip()
            category = str(extract.get("category", "general")).strip()
            if not title or not content:
                continue
            # Build a deterministic ID from session_id + title to avoid duplicates
            import hashlib
            synthetic_id = hashlib.md5(f"{session_id}:{title}".encode()).hexdigest()
            if synthetic_id in existing_ids:
                continue
            slug = _slug(title)
            filename = f"{synthetic_id[:8]}--{slug}.md"
            meta = {
                "id": synthetic_id,
                "title": title,
                "type": "session_extract",
                "category": category,
                "agent": "calls",
                "contributed_by": username,
                "source_id": session_id,
                "source_title": session_title,
                "tags": [],
                "products": [],
                "created_at": session.get("timestamp", ""),
            }
            path = CALLS_DIR / filename
            path.write_text(_write_fm(meta) + "\n\n" + content, encoding="utf-8")
            existing_ids.add(synthetic_id)
            print(f"  [ok]   calls/{filename} (from session: {session_title})")
            written += 1
    return written


def main() -> None:
    print("=== Cadence Vault Migration ===\n")

    # Phase A: Curated knowledge
    print("[1] Migrating curated knowledge files...")
    kb_count = migrate_knowledge_files()
    print(f"    → {kb_count} file(s) copied\n")

    # Phase B: Call learnings (all users)
    print("[2] Migrating call learnings (all users)...")
    calls_existing = _existing_ids(CALLS_DIR)
    calls_count = migrate_learnings_json(CALLS_LEARNINGS_DIR, "calls", calls_existing)
    print(f"    → {calls_count} entry/entries written\n")

    # Phase C: Session extracts
    print("[3] Migrating session knowledge_extracts...")
    session_count = migrate_session_extracts(calls_existing)
    print(f"    → {session_count} extract(s) written\n")

    # Phase D: Lead learnings (all users)
    print("[4] Migrating lead/campaign learnings (all users)...")
    lead_existing = _existing_ids(LEAD_DIR)
    lead_count = migrate_learnings_json(LEAD_LEARNINGS_DIR, "lead", lead_existing)
    print(f"    → {lead_count} entry/entries written\n")

    total = kb_count + calls_count + session_count + lead_count
    print(f"=== Done. {total} item(s) added to vault ===")
    print(f"    Vault location: {VAULT_DIR}")


if __name__ == "__main__":
    main()
