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

from paths import vault_dir

VAULT_DIR = vault_dir()

# Pillar 1 — Company Truth (locked, canonical)
COMPANY_DIR = VAULT_DIR / "company"
KNOWLEDGE_DIR = COMPANY_DIR / "knowledge"
ENTITIES_DIR = COMPANY_DIR / "entities"
GLOSSARY_DIR = COMPANY_DIR / "glossary"

# Pillar 2 — Dynamic Truth (grown from calls + leads at runtime)
DYNAMIC_DIR = VAULT_DIR / "dynamic"
CALLS_DIR = DYNAMIC_DIR / "calls"
LEAD_DIR = DYNAMIC_DIR / "lead"
DYNAMIC_GLOSSARY_DIR = DYNAMIC_DIR / "glossary"

#: Where a learning came from, and therefore which directory holds it.
#:
#: A closed vocabulary because the destination used to be inferred from the
#: free-text `agent` name — `CALLS_DIR if agent == "calls" else LEAD_DIR`. When
#: the calls agent was renamed to `call_analysis`, every learning Knowledge
#: Capture wrote fell through to the else-branch and was filed under leads,
#: unnoticed for a month, because a fallback cannot fail.
_LEARNING_DIRS: dict[str, Path] = {"call": CALLS_DIR, "lead": LEAD_DIR}

# Pillar 3 — Added Knowledge (user corrections, admin-gated)
ADDED_DIR = VAULT_DIR / "added"
ADDED_PENDING_DIR = ADDED_DIR / "pending"
ADDED_APPROVED_DIR = ADDED_DIR / "approved"
ADDED_REJECTED_DIR = ADDED_DIR / "rejected"

for _d in [
    VAULT_DIR,
    COMPANY_DIR, KNOWLEDGE_DIR, ENTITIES_DIR, GLOSSARY_DIR,
    DYNAMIC_DIR, CALLS_DIR, LEAD_DIR, DYNAMIC_GLOSSARY_DIR,
    ADDED_DIR, ADDED_PENDING_DIR, ADDED_APPROVED_DIR, ADDED_REJECTED_DIR,
]:
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
    # Acme products
    "White Rabbit Ecosystem":  ("product",   "white-rabbit"),
    "Open Time Server":        ("product",   "open-time-server"),
    "Open Timecard":           ("product",   "open-timecard"),
    "Clock Quorum":            ("product",   "clock-quorum"),
    "Clock Sync Software":     ("product",   "clock-sync-software"),
    "Time as a Service":       ("product",   "taas"),
    "Acme Mini":           ("product",   "acme-mini"),
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
    "Arclight Networks":                   ("customer",  "arclight-networks"),
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

        # Idempotency: if this entity already appears as a [[wikilink]] anywhere
        # in the body (any casing), skip — re-running must not add new links.
        if re.search(r"\[\[" + re.escape(entity) + r"\]\]", body, flags=re.IGNORECASE):
            # Still record the tag/product so frontmatter stays in sync
            if category == "product":
                if entity not in products:
                    products.append(entity)
            else:
                if tag not in tags:
                    tags.append(tag)
            continue

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
    description: str,
    content: str,
    category: str,
    origin: str,
    agent: str,
    contributed_by: str,
    source_id: str,
    source_title: str,
    tags: list[str] | None = None,
    products: list[str] | None = None,
) -> Path:
    """Write one learning entry to the Dynamic pillar.

    Auto-injects [[wikilinks]] for known entities and enriches frontmatter.
    Requires both `title` and `description` — every runtime write must carry
    a one-sentence summary used by Owl, Obsidian property views, and the
    admin UI. Returns the written file path.

    `origin` decides the directory and must name one of `_LEARNING_DIRS`;
    `agent` is attribution only. They are separate because who wrote a learning
    and where it belongs are different questions, and conflating them is what
    misfiled a month of writes.
    """
    if not title or not title.strip():
        raise ValueError("write_learning: title is required")
    if not description or not description.strip():
        raise ValueError("write_learning: description is required (one-sentence summary)")
    if origin not in _LEARNING_DIRS:
        raise ValueError(
            f"write_learning: origin must be one of {sorted(_LEARNING_DIRS)}, not {origin!r}"
        )

    enriched_body, detected_products, detected_tags = _inject_links_and_enrich_meta(
        content,
        existing_products=products or [],
        existing_tags=tags or [],
    )

    entry_id = uuid.uuid4().hex
    slug = _slug(title)
    filename = f"{entry_id[:8]}--{slug}.md"
    target_dir = _LEARNING_DIRS[origin]

    meta = {
        "id": entry_id,
        "title": title,
        "description": description.strip(),
        "tier": "dynamic",
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
    invalidate_vault_cache()
    return path


def write_glossary_term(
    *,
    term: str,
    description: str,
    body: str = "",
    source_id: str,
    source_title: str,
    contributed_by: str,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
) -> Path | None:
    """Write a dynamic glossary term into the Dynamic pillar if not already known.

    Skips if the term exists in either the Company-tier seed glossary
    (`company/glossary/`) or the Dynamic glossary (`dynamic/glossary/`).
    `description` is the short one/two-sentence summary surfaced everywhere.
    `body` is the full expanded entry (definition + Acme context + sales
    note + related products). If `body` is empty, `description` is used.
    Returns path or None if the term is already known.

    `source_title` is stored beside `source_id` deliberately. The call library
    trims at `MAX_SESSIONS` and deleting a call cleans nothing up, so a term
    outlives the record of where it came from; without the title captured here,
    a term whose call is gone can only show a bare hex id.
    """
    if not description or not description.strip():
        raise ValueError("write_glossary_term: description is required")

    slug = _slug(term)
    if (GLOSSARY_DIR / f"{slug}.md").exists() or (DYNAMIC_GLOSSARY_DIR / f"{slug}.md").exists():
        return None
    path = DYNAMIC_GLOSSARY_DIR / f"{slug}.md"
    meta = {
        "id": uuid.uuid4().hex,
        "title": term,
        "description": description.strip(),
        "tier": "dynamic",
        "type": "glossary",
        "aliases": aliases or [],
        "tags": tags or [],
        "first_seen_in": source_id,
        "source_title": source_title,
        "contributed_by": contributed_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    final_body = body.strip() if body and body.strip() else description.strip()
    path.write_text(_write_fm(meta) + "\n\n" + final_body, encoding="utf-8")
    invalidate_vault_cache()
    return path


# ---------------------------------------------------------------------------
# Added Knowledge — Pillar 3 (user corrections, admin-gated)
# ---------------------------------------------------------------------------

def write_added_knowledge(
    *,
    title: str,
    description: str,
    content: str,
    topic: str,
    what_owl_said: str,
    user_correction: str,
    submitted_by: str,
    session_id: str,
    suggested_source: str = "",
) -> Path:
    """Write a user-submitted correction into the Added pillar pending queue.

    The file lands in `added/pending/` and is NOT loaded by Owl until an admin
    moves it to `added/approved/` via `approve_added()`. Both `title` and
    `description` are required.
    """
    if not title or not title.strip():
        raise ValueError("write_added_knowledge: title is required")
    if not description or not description.strip():
        raise ValueError("write_added_knowledge: description is required")
    if not user_correction or not user_correction.strip():
        raise ValueError("write_added_knowledge: user_correction is required")

    enriched_body, detected_products, detected_tags = _inject_links_and_enrich_meta(
        content,
        existing_products=[],
        existing_tags=[],
    )

    entry_id = uuid.uuid4().hex
    slug = _slug(title)
    filename = f"{entry_id[:8]}--{slug}.md"
    path = ADDED_PENDING_DIR / filename

    meta = {
        "id": entry_id,
        "title": title,
        "description": description.strip(),
        "tier": "added",
        "status": "pending",
        "type": "correction",
        "topic": topic,
        "submitted_by": submitted_by,
        "session_id": session_id,
        "what_owl_said": what_owl_said,
        "user_correction": user_correction,
        "suggested_source": suggested_source,
        "tags": detected_tags,
        "products": detected_products,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(_write_fm(meta) + "\n\n" + enriched_body, encoding="utf-8")
    return path


def write_contribution(
    *,
    title: str,
    description: str,
    content: str,
    kind: str,
    contributed_by: str,
    entity_type: str = "",
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    products: list[str] | None = None,
    source: str = "",
    confidence: str = "medium",
    batch_id: str = "",
    display_name: str = "",
) -> Path:
    """Write one contributed knowledge entry into the Added pillar pending queue.

    The sibling of :func:`write_added_knowledge`, for knowledge someone hands
    over in bulk rather than a correction to something Owl said in a session. It
    lands in the same `added/pending/` queue and is **not** loaded by Owl until an
    admin approves it — `approve_added`, `reject_added`, `list_added` and the
    admin surface all work on frontmatter and do not care that `type` here is
    `contribution` rather than `correction`.

    `kind` records which part of the vault the knowledge is destined for. It is
    not acted on: filing into `company/` is a judgement an admin makes at
    approval, and guessing it at import would put unreviewed material into the
    canonical pillar.

    `contributed_by` is a **Cadence username**, not a display name: it is what
    `contributions_by` matches on to show a person their own work. `display_name`
    is the human form used in the provenance line that reaches Owl's prompt, and
    falls back to the username when it is not given.

    `content` is expected to have been through
    :func:`agents.shared.contributions.normalise_entry`, which demotes its
    headings so it cannot impersonate a section of Owl's assembled prompt.
    """
    if not title or not title.strip():
        raise ValueError("write_contribution: title is required")
    if not description or not description.strip():
        raise ValueError("write_contribution: description is required")
    if not content or not content.strip():
        raise ValueError("write_contribution: content is required")
    if not contributed_by or not contributed_by.strip():
        raise ValueError("write_contribution: contributed_by is required")

    enriched_body, detected_products, detected_tags = _inject_links_and_enrich_meta(
        content,
        existing_products=list(products or []),
        existing_tags=list(tags or []),
    )

    entry_id = uuid.uuid4().hex
    filename = f"{entry_id[:8]}--{_slug(title)}.md"
    path = ADDED_PENDING_DIR / filename

    meta = {
        "id": entry_id,
        "title": title.strip(),
        "description": description.strip(),
        "tier": "added",
        "status": "pending",
        "type": "contribution",
        "kind": kind,
        "entity_type": entity_type,
        "aliases": list(aliases or []),
        "contributed_by": contributed_by.strip(),
        "source": source.strip(),
        "confidence": confidence,
        "batch_id": batch_id,
        "tags": detected_tags,
        "products": detected_products,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # The provenance line is part of the body, not only the frontmatter, because
    # `_fmt_learning_for_context` renders the body into Owl's prompt under a
    # heading that says to treat the section as authoritative. Whose knowledge it
    # is should travel with it into that prompt.
    provenance = f"*Contributed by {(display_name or contributed_by).strip()}"
    if source.strip():
        provenance += f", from {source.strip()}"
    provenance += f". Confidence: {confidence}.*"

    path.write_text(
        _write_fm(meta) + "\n\n" + provenance + "\n\n" + enriched_body,
        encoding="utf-8",
    )
    return path


def _find_added(entry_id: str, *dirs: Path) -> Path | None:
    for d in dirs:
        for p in d.glob(f"{entry_id[:8]}--*.md"):
            return p
    return None


def approve_added(entry_id: str, *, reviewed_by: str, review_notes: str = "") -> Path:
    """Move a pending Added entry to `approved/`, stamping reviewer metadata.

    From the next Owl turn onward, the approved file is loaded into context.
    """
    src = _find_added(entry_id, ADDED_PENDING_DIR)
    if src is None:
        raise FileNotFoundError(f"No pending Added entry for id {entry_id}")
    text = src.read_text(encoding="utf-8")
    meta, body = _parse_fm(text)
    meta["status"] = "approved"
    meta["reviewed_by"] = reviewed_by
    meta["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    if review_notes:
        meta["review_notes"] = review_notes
    dst = ADDED_APPROVED_DIR / src.name
    dst.write_text(_write_fm(meta) + "\n\n" + body, encoding="utf-8")
    src.unlink()
    invalidate_vault_cache()
    return dst


def reject_added(entry_id: str, *, reviewed_by: str, review_notes: str = "") -> Path:
    """Move a pending Added entry to `rejected/`. Never loaded by Owl."""
    src = _find_added(entry_id, ADDED_PENDING_DIR)
    if src is None:
        raise FileNotFoundError(f"No pending Added entry for id {entry_id}")
    text = src.read_text(encoding="utf-8")
    meta, body = _parse_fm(text)
    meta["status"] = "rejected"
    meta["reviewed_by"] = reviewed_by
    meta["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    if review_notes:
        meta["review_notes"] = review_notes
    dst = ADDED_REJECTED_DIR / src.name
    dst.write_text(_write_fm(meta) + "\n\n" + body, encoding="utf-8")
    src.unlink()
    return dst


def list_added(status: str) -> list[dict]:
    """Return a list of Added-pillar files in the given status directory.

    status: 'pending' | 'approved' | 'rejected'
    Returns dicts with frontmatter fields + `body_preview`.
    """
    mapping = {
        "pending": ADDED_PENDING_DIR,
        "approved": ADDED_APPROVED_DIR,
        "rejected": ADDED_REJECTED_DIR,
    }
    if status not in mapping:
        raise ValueError(f"Invalid status {status!r}")
    out: list[dict] = []
    for p in sorted(mapping[status].glob("*.md"), reverse=True):
        try:
            text = p.read_text(encoding="utf-8")
            meta, body = _parse_fm(text)
            meta["_filename"] = p.name
            meta["body_preview"] = body.strip()[:300]
            out.append(meta)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Attribution — who contributed what
# ---------------------------------------------------------------------------
# Presentation only. The vault is global and every approved entry is in every
# user's context; these helpers answer "which of it is this person's", so their
# own work can be named as theirs rather than dissolving into the corpus. They
# filter nothing out of anybody's view.


def contributions_by(
    username: str,
    *,
    tags: list[str] | None = None,
    products: list[str] | None = None,
    max_added: int = 60,
) -> tuple[list["_Candidate"], set[str]]:
    """One person's approved entries, and the ids the shared section selected.

    Returns `(mine, selected_ids)`. `mine` is everything in `added/approved/`
    attributed to `username`, newest-scoring first. `selected_ids` is what
    `_build_added_section` chose for this turn with the same arguments, so a
    caller can tell which of `mine` is already quoted in the prompt and which
    would otherwise be missing.

    Matching is on `contributed_by`, falling back to `submitted_by` — bulk
    contributions carry the first, Owl-session corrections the second.
    """
    if not username or not username.strip():
        return [], set()

    _, selected = _build_added_section(tags, products, max_added)
    selected_ids = {c.entry_id for c in selected if c.entry_id}

    wanted = username.strip().casefold()
    mine: list[_Candidate] = []
    for path in ADDED_APPROVED_DIR.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            meta, body = _parse_fm(text)
            if not body.strip():
                continue
            owner = str(meta.get("contributed_by") or meta.get("submitted_by") or "").strip()
            if owner.casefold() != wanted:
                continue
            mine.append(
                _Candidate(
                    score=_score_candidate(meta, tags, products),
                    created_at=meta.get("created_at", ""),
                    title=meta.get("title", ""),
                    category=meta.get("category", ""),
                    contributed_by=owner,
                    tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
                    products=meta.get("products", []) if isinstance(meta.get("products"), list) else [],
                    body=body,
                    entry_id=meta.get("id", ""),
                )
            )
        except Exception:
            pass

    mine.sort(key=lambda c: (c.score, c.created_at), reverse=True)
    return mine, selected_ids


def format_for_context(candidate: "_Candidate") -> str:
    """One candidate rendered the way every vault section renders its entries."""
    return _fmt_learning_for_context(
        {
            "title": candidate.title,
            "category": candidate.category,
            "contributed_by": candidate.contributed_by,
            "created_at": candidate.created_at,
            "tags": candidate.tags,
            "products": candidate.products,
        },
        candidate.body,
    )


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
    #: The entry's vault id, when it has one. Added-pillar callers need to know
    #: *which* entries were selected, so a contributor's own unselected work can
    #: be carried separately; learnings never set it.
    entry_id: str = ""


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


# ---------------------------------------------------------------------------
# Composable section builders
# ---------------------------------------------------------------------------
# Each builder produces one assembled section (or None when empty), and takes an
# optional filter so the full vault (`load_vault_for_context`) and the scoped
# analyser vault (`load_vault_for_analysis`) share assembly logic. With every
# filter left as None the builders reproduce the original full-vault output
# byte-for-byte.

def _build_company_truth_section(
    file_filter: "Callable[[Path, dict], bool] | None" = None,
) -> str | None:
    """# Company Truth — every .md under company/, excluding entities/ and glossary/.

    `file_filter(path, meta)` decides inclusion; when None, every file is kept
    (and frontmatter is not even parsed, preserving the original behaviour).
    """
    excluded_subtrees = {ENTITIES_DIR.resolve(), GLOSSARY_DIR.resolve()}
    company_files: list[str] = []
    for path in sorted(COMPANY_DIR.rglob("*.md")):
        try:
            if any(parent.resolve() in excluded_subtrees for parent in path.parents):
                continue
            text = path.read_text(encoding="utf-8")
            if file_filter is not None:
                meta, _ = _parse_fm(text)
                if not file_filter(path, meta):
                    continue
            company_files.append(text)
        except Exception:
            pass
    if company_files:
        return "# Company Truth (canonical)\n\n" + "\n\n---\n\n".join(company_files)
    return None


def _build_entities_section(
    slug_filter: "set[str] | None" = None,
) -> tuple[str | None, set[str]]:
    """# Entity Reference — products, protocols, terms, customers.

    Returns (section, loaded_slugs). `slug_filter`, when given, restricts the
    section to those entity stems (used by the scoped analyser path).
    """
    entity_texts: dict[str, str] = {}
    loaded_entity_slugs: set[str] = set()
    for path in sorted(ENTITIES_DIR.glob("*.md")):
        try:
            if slug_filter is not None and path.stem not in slug_filter:
                continue
            text = path.read_text(encoding="utf-8")
            entity_texts[path.stem] = text
            loaded_entity_slugs.add(path.stem)
        except Exception:
            pass
    section = None
    if entity_texts:
        section = "# Entity Reference\n\n" + "\n\n---\n\n".join(entity_texts.values())
    return section, loaded_entity_slugs


def _build_glossary_section(
    name_filter: "Callable[[str, list], bool] | None" = None,
) -> str | None:
    """# Glossary — company seed first, dynamic terms second.

    `name_filter(term, aliases)` decides inclusion; when None, every term is kept.
    """
    glossary_lines: list[str] = []
    for glossary_dir in (GLOSSARY_DIR, DYNAMIC_GLOSSARY_DIR):
        for path in sorted(glossary_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
                meta, body = _parse_fm(text)
                term = meta.get("title", path.stem)
                aliases = meta.get("aliases", [])
                if name_filter is not None and not name_filter(term, aliases):
                    continue
                alias_str = (
                    f" (also: {', '.join(aliases)})"
                    if aliases and isinstance(aliases, list) and aliases
                    else ""
                )
                glossary_lines.append(f"**{term}**{alias_str}: {body.strip()}")
            except Exception:
                pass
    if glossary_lines:
        return "# Glossary\n\n" + "\n\n".join(glossary_lines)
    return None


def _build_learnings_section(
    tags: list[str] | None,
    products: list[str] | None,
    max_learnings: int,
) -> tuple[str | None, list["_Candidate"]]:
    """# Dynamic Truth — Team Learnings (scored subset).

    Returns (section, selected_candidates). Scoring/selection is unchanged from
    the original; `selected` is returned so the wikilink follow-up can run.
    """
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

    section = None
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
        section = (
            f"# Dynamic Truth — Team Learnings ({len(selected)} entries)\n\n"
            + "\n\n---\n\n".join(learning_blocks)
        )
    return section, selected


def _build_added_section(
    tags: list[str] | None,
    products: list[str] | None,
    max_added: int,
) -> tuple[str | None, list["_Candidate"]]:
    """# Approved Added Knowledge — admin-blessed corrections and contributions.

    Returns (section, selected). Scored exactly as the learnings section is, and
    for the same reason: the pillar is now bigger than the budget, so which
    entries reach the prompt has to be a decision rather than an accident.

    **It used to be an accident.** The selection was
    `sorted(ADDED_APPROVED_DIR.glob("*.md"), reverse=True)[:max_added]`, and the
    filenames it sorted are `{uuid4().hex[:8]}--{slug}.md` — so the sort key was
    random. Below the cap nobody noticed; above it, an import of two hundred
    entries would have put twenty arbitrary ones in front of Owl and silently
    discarded the rest. `list_added` still sorts that way, which is harmless
    because the admin queue shows every entry rather than a slice.

    `selected` is returned so a caller can tell which entries made it — the
    own-contributions block carries a contributor's *unselected* work, and needs
    to know which that is to avoid repeating what is already in the prompt.
    """
    candidates: list[_Candidate] = []
    for path in ADDED_APPROVED_DIR.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            meta, body = _parse_fm(text)
            if not body.strip():
                continue
            candidates.append(
                _Candidate(
                    score=_score_candidate(meta, tags, products),
                    created_at=meta.get("created_at", ""),
                    title=meta.get("title", ""),
                    category=meta.get("category", ""),
                    # Corrections carry `submitted_by`, contributions `contributed_by`.
                    contributed_by=meta.get("contributed_by") or meta.get("submitted_by", ""),
                    tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
                    products=meta.get("products", []) if isinstance(meta.get("products"), list) else [],
                    body=body,
                    entry_id=meta.get("id", ""),
                )
            )
        except Exception:
            pass

    candidates.sort(key=lambda c: (c.score, c.created_at), reverse=True)
    selected = candidates[:max_added]
    if not selected:
        return None, []

    blocks = [
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
    section = (
        f"# Approved Added Knowledge ({len(selected)} entries)\n\n"
        "*Admin-approved knowledge submitted by the team. Treat as authoritative.*\n\n"
        + "\n\n---\n\n".join(blocks)
    )
    return section, selected


def _build_referenced_entities_section(
    selected: list["_Candidate"],
    loaded_entity_slugs: set[str],
) -> str | None:
    """# Referenced Entities — entity files reached only via [[wikilinks]] in learnings.

    Mutates `loaded_entity_slugs` to record any newly loaded entity.
    """
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
        return (
            "# Referenced Entities (via links in learnings)\n\n"
            + "\n\n---\n\n".join(missing_entities)
        )
    return None


def load_vault_for_context(
    *,
    tags: list[str] | None = None,
    products: list[str] | None = None,
    max_learnings: int = 30,
    # Raised from 20 with the scoring fix. Entries are short — a correction is
    # two sentences — and the pillar is about to take bulk imports, so a budget
    # that small would discard most of what is contributed.
    max_added: int = 60,
) -> str:
    """Assemble Owl's full context across the three Cadence Knowledge pillars.

    Precedence (top of the assembled prompt → bottom):
      1. # Company Truth (canonical)        — vault/company/**/*.md
      2. # Entity Reference                  — vault/company/entities/
      3. # Glossary                          — company/glossary/ then dynamic/glossary/
      4. # Dynamic Truth — Team Learnings    — scored subset of dynamic/calls + dynamic/lead
      5. # Approved Added Knowledge          — vault/added/approved/ (admin-blessed)
      6. # Referenced Entities (via links)   — any entity files only reached via [[wikilinks]]

    Pending and rejected Added entries are NEVER loaded. `tags`/`products` only
    influence the learnings score (section 4); the other sections load in full.
    """
    parts: list[str] = []

    if (s := _build_company_truth_section()) is not None:
        parts.append(s)

    entities_section, loaded_entity_slugs = _build_entities_section()
    if entities_section is not None:
        parts.append(entities_section)

    if (s := _build_glossary_section()) is not None:
        parts.append(s)

    learnings_section, selected = _build_learnings_section(tags, products, max_learnings)
    if learnings_section is not None:
        parts.append(learnings_section)

    added_section, _selected_added = _build_added_section(tags, products, max_added)
    if added_section is not None:
        parts.append(added_section)

    if selected:
        if (s := _build_referenced_entities_section(selected, loaded_entity_slugs)) is not None:
            parts.append(s)

    return "\n\n---\n\n".join(parts) if parts else "No vault knowledge loaded."


# ---------------------------------------------------------------------------
# Transcript-scoped vault (analyser path)
# ---------------------------------------------------------------------------
# The call analyser only needs the slice of the vault a given call references.
# These helpers select entities, glossary terms, learnings, and company-truth
# docs by matching the transcript, cutting the assembled prefix from ~130k to
# ~30-40k tokens. Output is deterministic but transcript-dependent, so this
# path does NOT use the Anthropic prompt cache (see get_analysis_system_blocks).

# A short token is treated as an acronym (matched case-sensitively) when it is
# all-caps/digits with optional . / - separators — e.g. PTP, GNSS, 10GbE.
_ACRONYM_RE = re.compile(r"^[A-Z0-9][A-Z0-9./-]*$")

# Tags that appear on the majority of Company Truth docs (measured: ptp 41/47,
# gnss 40, holdover 33, …) or are structural rather than topical. They carry no
# signal for *which* docs to include, so they must not drive Company-Truth
# scoping — otherwise one mention of "PTP" pulls in nearly the whole tree. They
# still feed learnings scoring (which is capped), just not doc selection.
_COMPANY_TAG_STOPLIST = {
    "ptp", "gnss", "holdover", "ocxo", "rubidium", "pnt",
    "products", "website", "datasheet", "hardware", "software", "solution",
    "industry", "research", "reference", "platform", "downloads", "videos",
    "resources", "pricing-model",
}


def _norm_tag(t: str) -> str:
    """Normalise a frontmatter tag/product token. `_parse_fm` leaves quotes on
    list items (`["research", rubidium]` -> `'"research"'`, `'rubidium'`), so
    strip them and lowercase for reliable set intersection."""
    return t.strip().strip('"').strip("'").lower()


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _strip_parenthetical(title: str) -> list[str]:
    """Full title plus the inside/outside of a trailing parenthetical.

    "1PPS (One Pulse Per Second)" -> ["1PPS (One Pulse Per Second)", "1PPS", "One Pulse Per Second"]
    Entity `aliases` are empty on disk, so this is the main entity match surface.
    """
    title = (title or "").strip()
    forms = [title] if title else []
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", title)
    if m:
        outside, inside = m.group(1).strip(), m.group(2).strip()
        if outside:
            forms.append(outside)
        if inside:
            forms.append(inside)
    return forms


def _build_match_terms(title: str, aliases) -> list[str]:
    """Distinct surface forms to match a vault entry against a transcript."""
    terms: list[str] = list(_strip_parenthetical(title))
    if isinstance(aliases, list):
        for a in aliases:
            a = (a or "").strip().strip('"').strip("'")
            if a:
                terms.append(a)
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        k = t.lower()
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _compile_term_pattern(term: str):
    """Word-boundary matcher for one term, or None if too short to match safely.

    Short all-caps acronyms (<4 chars: PTP, STL, BBU) match case-sensitively so
    they don't fire inside ordinary words ("stl" in "install"); everything else
    matches case-insensitively.
    """
    if len(term) < 2:
        return None
    flags = 0 if (len(term) < 4 and _ACRONYM_RE.match(term)) else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", flags)


def _terms_match(transcript: str, terms: list[str]) -> bool:
    """True if any term hits the (original-case) transcript."""
    for term in terms:
        pat = _compile_term_pattern(term)
        if pat is not None and pat.search(transcript):
            return True
    return False


def _build_glossary_index() -> str | None:
    """A compact index of EVERY glossary term (names + aliases, no bodies).

    Cheap (~2-3k tokens for the whole glossary) but keeps the analyser aware of
    the full term vocabulary even when only a few full definitions are loaded —
    so it names concepts canonically and doesn't re-propose terms that already
    exist. Pairs with the full bodies of the matched terms.
    """
    lines: list[str] = []
    for glossary_dir in (GLOSSARY_DIR, DYNAMIC_GLOSSARY_DIR):
        for path in sorted(glossary_dir.glob("*.md")):
            try:
                meta, _ = _parse_fm(path.read_text(encoding="utf-8"))
                term = meta.get("title", path.stem)
                aliases = meta.get("aliases", [])
                alias_str = (
                    f" (also: {', '.join(aliases)})"
                    if aliases and isinstance(aliases, list) and aliases
                    else ""
                )
                lines.append(f"- {term}{alias_str}")
            except Exception:
                pass
    if lines:
        return "# Known Glossary Terms (index — names only)\n\n" + "\n".join(lines)
    return None


def load_vault_for_analysis(transcript: str, *, max_learnings: int = 20) -> str:
    """Assemble a transcript-scoped vault for the call analyser.

    Includes only the entities and glossary terms the transcript mentions, the
    learnings scored against their tags/products, plus an always-on Company
    Truth core (`company/knowledge/`) and any product/research docs whose
    tags/products intersect what the call references. Deterministic; no product
    catalogue (product fit is the opt-in endpoint's job).
    """
    text = transcript or ""
    parts: list[str] = []
    derived_tags: set[str] = set()
    derived_products: set[str] = set()

    # 1. Entities mentioned in the call — harvest their tags/products for scoring.
    matched_entity_slugs: set[str] = set()
    for path in sorted(ENTITIES_DIR.glob("*.md")):
        try:
            meta, _ = _parse_fm(path.read_text(encoding="utf-8"))
            title = meta.get("title", path.stem)
            if _terms_match(text, _build_match_terms(title, meta.get("aliases", []))):
                matched_entity_slugs.add(path.stem)
                for t in (meta.get("tags") or []):
                    if isinstance(t, str):
                        derived_tags.add(_norm_tag(t))
                if meta.get("entity_type") == "product":
                    derived_products.add(_norm_tag(title))
        except Exception:
            pass

    # 2. Glossary terms mentioned in the call — harvest their tags too.
    matched_glossary_titles: set[str] = set()
    for glossary_dir in (GLOSSARY_DIR, DYNAMIC_GLOSSARY_DIR):
        for path in sorted(glossary_dir.glob("*.md")):
            try:
                meta, _ = _parse_fm(path.read_text(encoding="utf-8"))
                title = meta.get("title", path.stem)
                if _terms_match(text, _build_match_terms(title, meta.get("aliases", []))):
                    matched_glossary_titles.add(title.strip().lower())
                    for t in (meta.get("tags") or []):
                        if isinstance(t, str):
                            derived_tags.add(_norm_tag(t))
            except Exception:
                pass

    # 3. Company Truth — always-on knowledge/ core + tag/product-matched docs.
    #    Generic tags (PTP, GNSS, …) are excluded from doc selection so a single
    #    common mention doesn't pull in the whole products/research tree.
    discriminating_tags = derived_tags - _COMPANY_TAG_STOPLIST

    def _company_filter(path: Path, meta: dict) -> bool:
        if _under(path, KNOWLEDGE_DIR):
            return True
        file_tags = {_norm_tag(t) for t in (meta.get("tags") or []) if isinstance(t, str)}
        if discriminating_tags & file_tags:
            return True
        file_products = {_norm_tag(p) for p in (meta.get("products") or []) if isinstance(p, str)}
        return bool(derived_products & file_products)

    if (s := _build_company_truth_section(file_filter=_company_filter)) is not None:
        parts.append(s)

    # 4. Entity Reference — ALL entities (only ~3.3k tokens, 24 files). Keeping
    #    the full product/protocol vocabulary prevents mis-naming and unsupported
    #    product claims; the A/B showed scoping this out cost groundedness.
    entities_section, loaded_entity_slugs = _build_entities_section()
    if entities_section is not None:
        parts.append(entities_section)

    # 5a. Known-terms index — every glossary term by name, so concepts are named
    #     canonically and new_terms aren't re-proposed.
    if (s := _build_glossary_index()) is not None:
        parts.append(s)

    # 5b. Glossary — full definitions for only the matched terms.
    if matched_glossary_titles:
        s = _build_glossary_section(
            name_filter=lambda term, _aliases: term.strip().lower() in matched_glossary_titles
        )
        if s is not None:
            parts.append(s)

    # 6. Learnings — scored against the tags/products the call surfaced.
    learnings_section, selected = _build_learnings_section(
        sorted(derived_tags), sorted(derived_products), max_learnings
    )
    if learnings_section is not None:
        parts.append(learnings_section)

    # 7. Referenced entities via [[wikilinks]] in selected learnings.
    if selected:
        s = _build_referenced_entities_section(selected, loaded_entity_slugs)
        if s is not None:
            parts.append(s)

    return "\n\n---\n\n".join(parts) if parts else "No vault knowledge loaded."


def load_vault_for_product_rec(
    *,
    product_name: str | None = None,
    concepts: list[str] | None = None,
) -> str:
    """Focused product context for the opt-in product-recommendation endpoint.

    Always loads the product entities (the catalogue is small) so the model sees
    the full product space; restricts Company Truth to the named product's docs
    when `product_name` is given, else to product/concept-tagged docs.
    """
    product_slugs: set[str] = set()
    for path in sorted(ENTITIES_DIR.glob("*.md")):
        try:
            meta, _ = _parse_fm(path.read_text(encoding="utf-8"))
            if meta.get("entity_type") == "product":
                product_slugs.add(path.stem)
        except Exception:
            pass

    target_product = _norm_tag(product_name) if product_name else None
    concept_tags = {_norm_tag(c) for c in (concepts or []) if isinstance(c, str)}

    def _company_filter(path: Path, meta: dict) -> bool:
        file_products = {_norm_tag(p) for p in (meta.get("products") or []) if isinstance(p, str)}
        file_tags = {_norm_tag(t) for t in (meta.get("tags") or []) if isinstance(t, str)}
        if target_product:
            return target_product in file_products or target_product == _norm_tag(meta.get("title", ""))
        # No product named: the product entities already enumerate the catalogue,
        # so include only the fit-relevant overviews (industries/solutions) plus
        # docs matching the call's concepts — not every datasheet.
        category = _norm_tag(meta.get("category", ""))
        folder = _norm_tag(meta.get("source_folder", ""))
        if category in {"industry", "solution"} or folder in {"industries", "solutions"}:
            return True
        return bool((concept_tags - _COMPANY_TAG_STOPLIST) & file_tags)

    parts: list[str] = []
    if (s := _build_company_truth_section(file_filter=_company_filter)) is not None:
        parts.append(s)
    entities_section, _slugs = _build_entities_section(slug_filter=product_slugs)
    if entities_section is not None:
        parts.append(entities_section)

    return "\n\n---\n\n".join(parts) if parts else "No product knowledge loaded."


# ---------------------------------------------------------------------------
# Prompt-cache support
# ---------------------------------------------------------------------------
# The Anthropic prompt cache requires byte-identical prefixes across requests
# within a 5-minute TTL. `load_vault_for_context` does I/O on every call and
# can include time-sensitive ordering, so we memoise the assembled string per
# username for the cache window.

import time as _time

_VAULT_SESSION_TTL_SECONDS = 5 * 60
_vault_session_cache: dict[str, tuple[float, str]] = {}


def load_vault_for_session(username: str) -> str:
    """Return a byte-stable vault assembly for `username` within the cache window.

    Used by chat/refine flows that want their system prompt prefix to hit the
    Anthropic prompt cache across consecutive requests. Outside the TTL the
    assembly is rebuilt from disk.
    """
    now = _time.time()
    cached = _vault_session_cache.get(username)
    if cached and (now - cached[0]) < _VAULT_SESSION_TTL_SECONDS:
        return cached[1]
    text = load_vault_for_context()
    _vault_session_cache[username] = (now, text)
    return text


def invalidate_vault_cache() -> None:
    """Drop all cached vault assemblies. Call after any write to dynamic/added pillars.

    The Dynamic pillar is team-wide, so a new learning from one user must
    surface in every other user's next Owl turn. Clearing the whole dict is
    cheap — each user just pays one fresh assembly on their next request.
    """
    _vault_session_cache.clear()

