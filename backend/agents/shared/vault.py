"""Shared vault utility for Cadence.

The vault is a directory of structured markdown files with YAML-ish frontmatter.
It is also a valid Obsidian vault — open backend/vault/ in Obsidian directly.

Every agent action from every user writes to this shared vault.
Attribution is preserved in frontmatter but the knowledge belongs to the system.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

VAULT_DIR = Path(__file__).parent.parent.parent / "vault"
KNOWLEDGE_DIR = VAULT_DIR / "knowledge"
ENTITIES_DIR = KNOWLEDGE_DIR / "entities"
GLOSSARY_DIR = KNOWLEDGE_DIR / "glossary"
CALLS_DIR = VAULT_DIR / "calls"
LEAD_DIR = VAULT_DIR / "lead"

for _d in [VAULT_DIR, KNOWLEDGE_DIR, ENTITIES_DIR, GLOSSARY_DIR, CALLS_DIR, LEAD_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Entity registry
#
# Every entry here becomes a [[wikilink]] when detected in learning text.
# Sorted longest-first at runtime to prevent partial matches.
#
# Format: "Canonical Name": ("category", "tag-slug")
# category "product"   → name added to products[] frontmatter
# category anything else → slug added to tags[] frontmatter
# ---------------------------------------------------------------------------

_LINK_ENTITIES: dict[str, tuple[str, str]] = {
    # Timebeat products
    "White Rabbit Ecosystem":  ("product",   "white-rabbit"),
    "Open Time Server":        ("product",   "open-time-server"),
    "Open Timecard":           ("product",   "open-timecard"),
    "Clock Quorum":            ("product",   "clock-quorum"),
    "Clock Sync Software":     ("product",   "clock-sync-software"),
    "Time as a Service":       ("product",   "taas"),
    "Timebeat Mini":           ("product",   "timebeat-mini"),
    "P2P Squared":             ("product",   "p2p-squared"),
    "PTP Squared":             ("product",   "ptp-squared"),
    "White Rabbit":            ("product",   "white-rabbit"),
    "vGMC":                    ("product",   "vgmc"),
    "TaaS":                    ("product",   "taas"),
    # Protocols
    "Precision Time Protocol": ("protocol",  "ptp"),
    "Synchronous Ethernet":    ("protocol",  "synce"),
    "Grandmaster Clock":       ("term",      "grandmaster"),
    "Boundary Clock":          ("term",      "boundary-clock"),
    "OSNMA":                   ("protocol",  "osnma"),
    "GNSS":                    ("protocol",  "gnss"),
    "SyncE":                   ("protocol",  "synce"),
    "1PPS":                    ("protocol",  "1pps"),
    "STL":                     ("protocol",  "stl"),
    "PTP":                     ("protocol",  "ptp"),
    # Technical terms
    "PTM":                     ("term",      "ptm"),
    "PNT":                     ("term",      "pnt"),
    "BBU":                     ("term",      "bbu"),
    "TDD":                     ("term",      "tdd-5g"),
    "FDD":                     ("term",      "fdd"),
    "OCXO":                    ("term",      "ocxo"),
    "DOXO":                    ("term",      "doxo"),
    "Rubidium":                ("term",      "rubidium"),
    "Holdover":                ("term",      "holdover"),
    # Regulatory
    "MiFID II":                ("regulatory","mifid-ii"),
    "FINRA":                   ("regulatory","finra"),
    "ISO 9001":                ("regulatory","iso-9001"),
    "DORA":                    ("regulatory","dora"),
    # Key customers / partners
    "Nokia":                   ("customer",  "nokia"),
    "Microsoft":               ("customer",  "microsoft"),
    "Green Key":               ("customer",  "green-key"),
    "McLaren":                 ("customer",  "mclaren"),
    "Keysight":                ("customer",  "keysight"),
    "Equinix":                 ("customer",  "equinix"),
    "Meta":                    ("customer",  "meta"),
}

# Sorted longest-first to prevent partial matches (e.g. "White Rabbit" before "White Rabbit Ecosystem")
_SORTED_ENTITIES = sorted(_LINK_ENTITIES.keys(), key=len, reverse=True)


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:55]


def _fmt_list(items: list) -> str:
    if not items:
        return "[]"
    safe = [str(i).replace(",", " ").replace("]", "").replace("[", "") for i in items]
    return "[" + ", ".join(safe) + "]"


def _write_fm(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}: {_fmt_list(value)}")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            v = str(value)
            if any(c in v for c in [':', '#', '{', '}', '&', '*', '?', '|', '<', '>', '=', '!', '%', '@', '`']):
                v = '"' + v.replace('"', '\\"') + '"'
            lines.append(f"{key}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _parse_fm(text: str) -> tuple[dict, str]:
    """Parse frontmatter. Returns (metadata_dict, body_text)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta: dict = {}
    for line in fm_block.split("\n"):
        if ": " not in line:
            continue
        key, _, raw = line.partition(": ")
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1]
            meta[key] = [item.strip() for item in inner.split(",") if item.strip()] if inner.strip() else []
        else:
            meta[key] = raw.strip('"')
    return meta, body


# ---------------------------------------------------------------------------
# Link injection
# ---------------------------------------------------------------------------

def _inject_links_and_enrich_meta(
    body: str,
    existing_products: list[str],
    existing_tags: list[str],
) -> tuple[str, list[str], list[str]]:
    """Scan body for known entities, inject [[wikilinks]], return enriched products and tags.

    Uses negative lookbehind/lookahead to avoid re-linking already-linked text.
    Processes longest entity names first to prevent partial matches.
    """
    products: list[str] = list(existing_products)
    tags: list[str] = list(existing_tags)

    for entity in _SORTED_ENTITIES:
        category, tag = _LINK_ENTITIES[entity]

        # Regex: word-boundary match, not already inside [[ ]]
        # (?<!\[) avoids matching inside existing [[links]]
        pattern = r"(?<!\[)\b(" + re.escape(entity) + r")\b(?!\])"
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if not match:
            continue

        # Inject wikilink on first occurrence only (preserve original casing for display)
        original = match.group(1)
        body = body[: match.start()] + f"[[{original}]]" + body[match.end() :]

        # Update frontmatter metadata
        if category == "product":
            if entity not in products:
                products.append(entity)
        else:
            if tag not in tags:
                tags.append(tag)

    return body, products, tags


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def write_learning(
    *,
    title: str,
    content: str,
    category: str,
    agent: str,
    contributed_by: str,
    source_id: str,
    source_title: str,
    tags: list[str] | None = None,
    products: list[str] | None = None,
) -> Path:
    """Write one learning entry to the vault.

    Auto-injects [[wikilinks]] for known entities and enriches frontmatter.
    Returns the written file path.
    """
    enriched_body, detected_products, detected_tags = _inject_links_and_enrich_meta(
        content,
        existing_products=products or [],
        existing_tags=tags or [],
    )

    entry_id = uuid.uuid4().hex
    slug = _slug(title)
    filename = f"{entry_id[:8]}--{slug}.md"
    target_dir = CALLS_DIR if agent == "calls" else LEAD_DIR

    meta = {
        "id": entry_id,
        "title": title,
        "type": "learning",
        "category": category,
        "agent": agent,
        "contributed_by": contributed_by,
        "source_id": source_id,
        "source_title": source_title,
        "tags": detected_tags,
        "products": detected_products,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = target_dir / filename
    path.write_text(_write_fm(meta) + "\n\n" + enriched_body, encoding="utf-8")
    return path


def write_entity(
    *,
    title: str,
    entity_type: str,
    description: str,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
) -> Path:
    """Write a curated entity file (product / term / protocol / customer).

    Entity files are the link targets for [[wikilinks]] in learning entries.
    Idempotent: overwrites if the file already exists (entity definitions can be updated).
    """
    slug = _slug(title)
    path = ENTITIES_DIR / f"{slug}.md"
    meta = {
        "id": uuid.uuid4().hex,
        "title": title,
        "type": "entity",
        "entity_type": entity_type,
        "aliases": aliases or [],
        "tags": tags or [],
    }
    path.write_text(_write_fm(meta) + "\n\n" + description.strip(), encoding="utf-8")
    return path


def write_glossary_term(
    *,
    term: str,
    definition: str,
    context: str = "",
    source_id: str,
    contributed_by: str,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
) -> Path | None:
    """Write a dynamic glossary term if it does not already exist.

    Returns path or None if the term is already known.
    """
    slug = _slug(term)
    path = GLOSSARY_DIR / f"{slug}.md"
    if path.exists():
        return None
    meta = {
        "id": uuid.uuid4().hex,
        "title": term,
        "type": "glossary",
        "aliases": aliases or [],
        "tags": tags or [],
        "first_seen_in": source_id,
        "contributed_by": contributed_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    body = definition + ("\n\n" + context if context else "")
    path.write_text(_write_fm(meta) + "\n\n" + body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Retrofitting — enrich existing files in place
# ---------------------------------------------------------------------------

def retrofit_learning_file(path: Path) -> bool:
    """Inject [[wikilinks]] and update products/tags in an existing vault learning file.

    Returns True if the file was modified.
    """
    try:
        original = path.read_text(encoding="utf-8")
        meta, body = _parse_fm(original)
        if not body.strip():
            return False

        enriched_body, new_products, new_tags = _inject_links_and_enrich_meta(
            body,
            existing_products=meta.get("products", []) if isinstance(meta.get("products"), list) else [],
            existing_tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
        )

        # Only rewrite if something changed
        if enriched_body == body and new_products == meta.get("products", []) and new_tags == meta.get("tags", []):
            return False

        meta["products"] = new_products
        meta["tags"] = new_tags
        path.write_text(_write_fm(meta) + "\n\n" + enriched_body, encoding="utf-8")
        return True
    except Exception as e:
        print(f"  [err] {path.name}: {e}")
        return False


def retrofit_all_learning_files() -> int:
    """Retrofit all existing learning files with [[wikilinks]] and enriched frontmatter.

    Returns count of files modified.
    """
    modified = 0
    for subdir in [CALLS_DIR, LEAD_DIR]:
        for path in sorted(subdir.glob("*.md")):
            if retrofit_learning_file(path):
                modified += 1
    return modified


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    score: float
    created_at: str
    title: str
    category: str
    contributed_by: str
    tags: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    body: str = ""


def _score_candidate(meta: dict, tags: list[str] | None, products: list[str] | None) -> float:
    score = 0.0
    if tags:
        file_tags = meta.get("tags", [])
        if isinstance(file_tags, list):
            score += len(set(t.lower() for t in tags) & set(t.lower() for t in file_tags))
    if products:
        file_products = meta.get("products", [])
        if isinstance(file_products, list):
            score += len(set(p.lower() for p in products) & set(p.lower() for p in file_products)) * 2
    return score


def _extract_wikilinks(text: str) -> list[str]:
    """Return all [[link targets]] found in text."""
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def _fmt_learning_for_context(meta: dict, body: str) -> str:
    title = meta.get("title", "Untitled")
    category = meta.get("category", "")
    contributed_by = meta.get("contributed_by", "")
    tags = meta.get("tags", [])
    products = meta.get("products", [])
    created = meta.get("created_at", "")[:10]

    meta_parts = []
    if category:
        meta_parts.append(f"category: {category}")
    if contributed_by:
        meta_parts.append(f"by: {contributed_by}")
    if created:
        meta_parts.append(f"date: {created}")
    if products and isinstance(products, list) and products:
        meta_parts.append(f"products: {', '.join(products)}")
    if tags and isinstance(tags, list) and tags:
        meta_parts.append(f"tags: {', '.join(tags)}")

    header = f"### {title}"
    if meta_parts:
        header += f"\n*{' | '.join(meta_parts)}*"
    return header + "\n\n" + body.strip()


def load_vault_for_context(
    *,
    tags: list[str] | None = None,
    products: list[str] | None = None,
    max_learnings: int = 30,
) -> str:
    """Load vault content for injection into a system prompt.

    Returns:
      1. Curated KB files (always loaded)
      2. Entity files — product/term/protocol definitions (always loaded)
      3. Dynamic glossary terms (from runtime new_terms extraction)
      4. Top-scored empirical learnings (ranked by entity overlap + recency)
      5. Any entity files referenced by [[wikilinks]] in selected learnings
         that weren't already loaded — ensuring linked context is co-present
    """
    parts: list[str] = []
    loaded_entity_slugs: set[str] = set()

    # 1. Curated knowledge files
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 2. Entity files (products, protocols, terms, customers)
    entity_texts: dict[str, str] = {}
    for path in sorted(ENTITIES_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            entity_texts[path.stem] = text
            loaded_entity_slugs.add(path.stem)
        except Exception:
            pass
    if entity_texts:
        parts.append(
            "# Entity Reference\n\n"
            + "\n\n---\n\n".join(entity_texts.values())
        )

    # 3. Dynamic glossary terms
    glossary_lines: list[str] = []
    for path in sorted(GLOSSARY_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            meta, body = _parse_fm(text)
            term = meta.get("title", path.stem)
            aliases = meta.get("aliases", [])
            alias_str = (
                f" (also: {', '.join(aliases)})"
                if aliases and isinstance(aliases, list) and aliases
                else ""
            )
            glossary_lines.append(f"**{term}**{alias_str}: {body.strip()}")
        except Exception:
            pass
    if glossary_lines:
        parts.append("# Vault Glossary\n\n" + "\n\n".join(glossary_lines))

    # 4. Empirical learnings — scored and limited
    candidates: list[_Candidate] = []
    for subdir in [CALLS_DIR, LEAD_DIR]:
        for path in subdir.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
                meta, body = _parse_fm(text)
                if not body.strip():
                    continue
                score = _score_candidate(meta, tags, products)
                candidates.append(
                    _Candidate(
                        score=score,
                        created_at=meta.get("created_at", ""),
                        title=meta.get("title", ""),
                        category=meta.get("category", ""),
                        contributed_by=meta.get("contributed_by", ""),
                        tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
                        products=meta.get("products", []) if isinstance(meta.get("products"), list) else [],
                        body=body,
                    )
                )
            except Exception:
                pass

    candidates.sort(key=lambda c: (c.score, c.created_at), reverse=True)
    selected = candidates[:max_learnings]

    if selected:
        learning_blocks = [
            _fmt_learning_for_context(
                {
                    "title": c.title,
                    "category": c.category,
                    "contributed_by": c.contributed_by,
                    "created_at": c.created_at,
                    "tags": c.tags,
                    "products": c.products,
                },
                c.body,
            )
            for c in selected
        ]
        parts.append(
            f"# Team Learnings from Cadence ({len(selected)} entries)\n\n"
            + "\n\n---\n\n".join(learning_blocks)
        )

        # 5. Follow [[wikilinks]] — pull in any referenced entity not yet loaded
        linked_refs: set[str] = set()
        for c in selected:
            for link in _extract_wikilinks(c.body):
                linked_refs.add(_slug(link))

        missing_entities: list[str] = []
        for ref_slug in linked_refs:
            if ref_slug not in loaded_entity_slugs:
                entity_path = ENTITIES_DIR / f"{ref_slug}.md"
                if entity_path.exists():
                    try:
                        missing_entities.append(entity_path.read_text(encoding="utf-8"))
                        loaded_entity_slugs.add(ref_slug)
                    except Exception:
                        pass
        if missing_entities:
            parts.append(
                "# Referenced Entities (via links in learnings)\n\n"
                + "\n\n---\n\n".join(missing_entities)
            )

    return "\n\n---\n\n".join(parts) if parts else "No vault knowledge loaded."
