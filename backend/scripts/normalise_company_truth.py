"""Normalise Company-Truth markdown files in place.

Walks `backend/vault/company/` and, for every `.md` file outside the curated
`entities/`, `glossary/`, and `knowledge/` subtrees:

  1. Ensures YAML frontmatter exists with `tier: company`, `locked: true`,
     `title`, `description`, `id`, `source_folder`, and `ingested_at`.
  2. Backfills a missing `description` from the first non-heading line of body.
  3. Injects `[[wikilinks]]` for known entities so the Obsidian graph
     connects Company Truth to entities, learnings, and approved corrections.

The script is idempotent and only modifies files that change. Re-run any time
new folders are added under `vault/company/`.

Usage (from repo root, with venv active):

    python3 backend/scripts/normalise_company_truth.py
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Make backend/ importable when run from anywhere
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.shared.vault import (  # noqa: E402
    COMPANY_DIR, ENTITIES_DIR, GLOSSARY_DIR, KNOWLEDGE_DIR,
    _parse_fm, _write_fm, _inject_links_and_enrich_meta, _slug,
)

# These curated subtrees are already well-formed; the normaliser skips them.
SKIP_DIRS = {ENTITIES_DIR.resolve(), GLOSSARY_DIR.resolve(), KNOWLEDGE_DIR.resolve()}


def _first_non_heading_line(body: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("---"):
            continue
        return line[:280]
    return ""


def _title_from_body(body: str, fallback: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _is_under(path: Path, parents: set[Path]) -> bool:
    rp = path.resolve()
    for parent in rp.parents:
        if parent in parents:
            return True
    return False


def normalise_file(path: Path) -> tuple[bool, str]:
    """Return (modified, reason)."""
    original = path.read_text(encoding="utf-8")
    meta, body = _parse_fm(original)
    had_fm = original.startswith("---")
    changed = False
    reasons: list[str] = []

    # Determine the source_folder (the top-level dir under company/)
    rel = path.resolve().relative_to(COMPANY_DIR.resolve())
    source_folder = rel.parts[0] if rel.parts else ""

    if not had_fm:
        meta = {
            "id": uuid.uuid4().hex,
            "title": _title_from_body(body, path.stem.replace("-", " ").title()),
            "description": "",
            "tier": "company",
            "source_folder": source_folder,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "locked": True,
        }
        changed = True
        reasons.append("added frontmatter")

    # Required fields
    if "id" not in meta or not str(meta.get("id", "")).strip():
        meta["id"] = uuid.uuid4().hex
        changed = True
        reasons.append("added id")
    if "title" not in meta or not str(meta.get("title", "")).strip():
        meta["title"] = _title_from_body(body, path.stem.replace("-", " ").title())
        changed = True
        reasons.append("added title")
    if meta.get("tier") != "company":
        meta["tier"] = "company"
        changed = True
        reasons.append("set tier=company")
    if not meta.get("locked"):
        meta["locked"] = True
        changed = True
        reasons.append("set locked=true")
    if "source_folder" not in meta or not str(meta.get("source_folder", "")).strip():
        meta["source_folder"] = source_folder
        changed = True
        reasons.append("added source_folder")
    if "ingested_at" not in meta or not str(meta.get("ingested_at", "")).strip():
        meta["ingested_at"] = datetime.now(timezone.utc).isoformat()
        changed = True
        reasons.append("added ingested_at")
    if not str(meta.get("description", "")).strip():
        backfill = _first_non_heading_line(body)
        if backfill:
            meta["description"] = backfill
            changed = True
            reasons.append("backfilled description")

    # Wikilink injection across body
    new_body, products, tags = _inject_links_and_enrich_meta(
        body,
        existing_products=meta.get("products", []) if isinstance(meta.get("products"), list) else [],
        existing_tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
    )
    if new_body != body:
        body = new_body
        meta["products"] = products
        meta["tags"] = tags
        changed = True
        reasons.append("injected wikilinks")

    if changed:
        path.write_text(_write_fm(meta) + "\n\n" + body.lstrip("\n"), encoding="utf-8")
    return changed, ", ".join(reasons) if reasons else "no change"


def main() -> int:
    if not COMPANY_DIR.exists():
        print(f"[normalise] {COMPANY_DIR} does not exist")
        return 1

    total = 0
    changed = 0
    skipped = 0

    for path in sorted(COMPANY_DIR.rglob("*.md")):
        if _is_under(path, SKIP_DIRS):
            skipped += 1
            continue
        total += 1
        was_changed, reason = normalise_file(path)
        rel = path.relative_to(COMPANY_DIR)
        marker = "✓" if was_changed else "·"
        print(f"  {marker} {rel} — {reason}")
        if was_changed:
            changed += 1

    print(f"\n[normalise] processed {total} files, changed {changed}, skipped {skipped} curated files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
