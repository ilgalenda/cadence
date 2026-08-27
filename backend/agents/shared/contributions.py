"""Validation for knowledge contributed from outside Cadence.

A contribution is a batch of knowledge someone hands over — typically exported
from their own Claude — to be folded into the Cadence vault. It rides the
existing Added pillar: entries land in `added/pending/`, Owl cannot see them, and
they become part of its context only once an admin approves them. Nothing here
invents a second review queue; `approve_added`, `reject_added`, `list_added` and
the admin surface already work on frontmatter and are indifferent to the entry's
`type`.

**The content is untrusted, and this module is where that is enforced.** It comes
from a model, in a file, from another person, and once approved it is pasted
verbatim into Owl's prompt under a heading that tells Owl to *"Treat as
authoritative"* (`vault._build_added_section`). Two consequences:

  * **Headings are demoted.** `_fmt_learning_for_context` renders a contribution
    under `###`, so a body containing `# Company Truth` would outrank its own
    container and impersonate one of the prompt's real sections. Every heading in
    contributed markdown is pushed below `###` so it cannot.
  * **Instruction-shaped content is refused, not stripped.** An entry that reads
    like it is addressing the model rather than describing the world is reported
    for a human to look at. Silently sanitising it would hide the fact that
    somebody sent it, and the interesting signal is that it was sent at all.

Neither is a claim to have solved prompt injection. The review gate is the real
control; these two make the gate harder to walk past.

Pure functions only — no filesystem, no vault writes. `vault.write_contribution`
does the writing, and `import_contributions.py` is the operator's entry point.
"""
from __future__ import annotations

import re

#: The vault areas a contribution can be destined for. `kind` picks the shape the
#: entry must satisfy and, on approval, where the knowledge belongs. It is
#: recorded rather than acted on at import: everything lands in the Added pending
#: queue regardless, because filing into `company/` is a decision an admin makes.
KINDS = ("glossary", "entity", "knowledge", "research")

MAX_TITLE = 120
MAX_DESCRIPTION = 400
MAX_CONTENT = 20_000
MAX_ENTRIES = 500

CONFIDENCES = ("high", "medium", "low")

#: Phrases that read as an instruction to a model rather than a statement about
#: the world. Deliberately short and specific: a list long enough to catch
#: everything would reject honest writing about prompting, which — in a company
#: that builds agents — is knowledge worth contributing.
_INSTRUCTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "disregard previous",
    "you are now",
    "new instructions:",
    "system prompt",
    "</system>",
    "<system>",
)

#: A body impersonating one of the assembled prompt's own section headings.
_SECTION_IMPERSONATION = re.compile(
    r"^#{1,2}\s*(company truth|entity reference|glossary|dynamic truth"
    r"|approved added knowledge|referenced entities)\b",
    re.IGNORECASE | re.MULTILINE,
)

_HEADING = re.compile(r"^(#{1,6})(\s)", re.MULTILINE)


def demote_headings(markdown: str) -> str:
    """Push every heading below `###`, the level a contribution is rendered at.

    `#` and `##` become `###`; deeper headings keep their relative depth as far
    as `######`, which is as deep as markdown goes. Structure the contributor
    intended survives; the ability to outrank the container does not.
    """
    def _demote(match: re.Match) -> str:
        depth = min(len(match.group(1)) + 2, 6)
        return "#" * depth + match.group(2)

    return _HEADING.sub(_demote, markdown)


def suspicious_spans(text: str) -> list[str]:
    """Reasons this text reads as addressed to a model. Empty when it does not."""
    found: list[str] = []
    lowered = text.lower()
    for marker in _INSTRUCTION_MARKERS:
        if marker in lowered:
            found.append(f"contains {marker!r}")
    if _SECTION_IMPERSONATION.search(text):
        found.append("contains a heading that impersonates a prompt section")
    return found


def validate_entry(entry: object, index: int) -> list[str]:
    """Every problem with one entry, as operator-readable strings.

    All problems at once rather than the first: someone fixing an export wants
    the whole list, not to run the importer eleven times.
    """
    where = f"entry {index}"
    if not isinstance(entry, dict):
        return [f"{where}: must be an object, got {type(entry).__name__}"]

    problems: list[str] = []
    title = str(entry.get("title") or "").strip()
    if title:
        where = f"entry {index} ({title[:60]!r})"
    else:
        problems.append(f"{where}: `title` is required")

    kind = entry.get("kind")
    if kind not in KINDS:
        problems.append(f"{where}: `kind` must be one of {', '.join(KINDS)}, got {kind!r}")

    description = str(entry.get("description") or "").strip()
    if not description:
        problems.append(f"{where}: `description` is required — one line saying what this is")

    content = str(entry.get("content") or "").strip()
    if not content:
        problems.append(f"{where}: `content` is required — the knowledge itself, as markdown")

    if len(title) > MAX_TITLE:
        problems.append(f"{where}: `title` is longer than {MAX_TITLE} characters")
    if len(description) > MAX_DESCRIPTION:
        problems.append(f"{where}: `description` is longer than {MAX_DESCRIPTION} characters")
    if len(content) > MAX_CONTENT:
        problems.append(
            f"{where}: `content` is longer than {MAX_CONTENT} characters — split it into "
            "several entries, one idea each"
        )

    if kind == "entity" and not str(entry.get("entity_type") or "").strip():
        problems.append(f"{where}: `entity_type` is required when kind is 'entity'")

    for field in ("aliases", "tags", "products"):
        value = entry.get(field, [])
        if value in (None, ""):
            continue
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            problems.append(f"{where}: `{field}` must be a list of strings")

    confidence = entry.get("confidence")
    if confidence not in (None, "", *CONFIDENCES):
        problems.append(f"{where}: `confidence` must be one of {', '.join(CONFIDENCES)}")

    for reason in suspicious_spans(f"{title}\n{description}\n{content}"):
        problems.append(f"{where}: refused — {reason}")

    return problems


def validate_batch(payload: object) -> tuple[list[dict], list[str]]:
    """Split a parsed contributions file into usable entries and problems.

    Returns `(entries, problems)`. Entries are returned even when other entries
    failed, so one malformed record in a batch of two hundred does not cost the
    other hundred and ninety-nine — but the caller is expected to show the
    problems and let a person decide before writing anything.
    """
    if not isinstance(payload, dict):
        return [], ["the file must contain a JSON object at the top level"]

    problems: list[str] = []
    if not str(payload.get("contributed_by") or "").strip():
        problems.append("`contributed_by` is required — who this knowledge came from")

    raw = payload.get("entries")
    if not isinstance(raw, list):
        return [], problems + ["`entries` is required and must be a list"]
    if not raw:
        return [], problems + ["`entries` is empty — nothing to import"]
    if len(raw) > MAX_ENTRIES:
        return [], problems + [f"`entries` has more than {MAX_ENTRIES} items; split the file"]

    good: list[dict] = []
    seen_titles: set[str] = set()
    for index, entry in enumerate(raw, start=1):
        entry_problems = validate_entry(entry, index)
        if entry_problems:
            problems.extend(entry_problems)
            continue

        title = str(entry["title"]).strip()
        key = title.casefold()
        if key in seen_titles:
            problems.append(f"entry {index} ({title[:60]!r}): duplicate title in this file")
            continue
        seen_titles.add(key)
        good.append(normalise_entry(entry))

    return good, problems


def normalise_entry(entry: dict) -> dict:
    """One validated entry, trimmed and with its markdown made safe to embed."""
    def _list(field: str) -> list[str]:
        value = entry.get(field) or []
        return [v.strip() for v in value if isinstance(v, str) and v.strip()]

    return {
        "kind": entry["kind"],
        "title": str(entry["title"]).strip(),
        "description": str(entry["description"]).strip(),
        "content": demote_headings(str(entry["content"]).strip()),
        "entity_type": str(entry.get("entity_type") or "").strip(),
        "aliases": _list("aliases"),
        "tags": _list("tags"),
        "products": _list("products"),
        "source": str(entry.get("source") or "").strip(),
        "confidence": str(entry.get("confidence") or "").strip() or "medium",
    }
