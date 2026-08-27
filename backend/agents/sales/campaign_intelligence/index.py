"""The index of everything the team has learned on a call — titles only.

Campaign Intelligence has to answer "what came up last time we sold into finance",
and the corpus it must answer from cannot be filtered for it. Of the 281 analysed
call learnings in the vault, 110 carry no tags, 219 name no product, and **none
carries a vertical**. So the tag-scored selection the rest of the platform uses
(`vault._score_candidate`) has nothing to score on here.

What the corpus does have is titles, and they are full descriptive sentences —
*"NRE framing from a low-volume OEM customer: Raphaël modelled the conversation
correctly"*. An index of those is small enough to show in full and specific enough
to choose from. So the agent reads the whole index and picks, rather than a
keyword filter guessing on its behalf.

This module is the deterministic half of that: it builds the index, renders it,
resolves a selection back to files, and loads only the bodies chosen. No LLM, no
network, no writes — which is what makes the retrieval decision testable.

**Handles are ordinals, not ids.** The model picks by line number. Vault ids are
32 hex characters; 281 of them cost far more to show and to echo back than
`1..281`, and a mistyped ordinal is out of range rather than a plausible-looking
id pointing at the wrong call. Ordinals are per-call only and never persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agents.shared.vault import (
    CALLS_DIR,
    LEAD_DIR,
    _fmt_learning_for_context as format_learning,
    _parse_fm as parse_frontmatter,
)

#: The vault directories holding what agents learned at runtime — calls and leads.
#: Company Truth and the glossary are not conversations, so they are not recall.
SOURCE_DIRS = (CALLS_DIR, LEAD_DIR)


@dataclass(frozen=True)
class Learning:
    """One entry in the index. Everything except the body, which is loaded later."""

    id: str
    title: str
    category: str
    tags: tuple[str, ...]
    products: tuple[str, ...]
    created_at: str
    path: Path


def _str_list(value) -> tuple[str, ...]:
    """Frontmatter lists are best-effort; anything else reads as empty."""
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _learning_from(path: Path) -> Learning | None:
    """Read one file into an index row, or None when it cannot contribute.

    A file with no body is skipped — it has nothing to recall — matching how
    `vault._build_learnings_section` treats the same corpus. An unreadable file is
    skipped rather than raised: one bad file must not cost the other 280.
    """
    try:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not body.strip():
        return None

    return Learning(
        id=str(meta.get("id") or path.stem),
        # Falling back to the stem keeps an untitled learning selectable instead of
        # invisible; the stems are slugged titles, so they still read.
        title=str(meta.get("title") or path.stem).strip(),
        category=str(meta.get("category") or "").strip(),
        tags=_str_list(meta.get("tags")),
        products=_str_list(meta.get("products")),
        created_at=str(meta.get("created_at") or "").strip(),
        path=path,
    )


# --------------------------------------------------------------------------- #
# Cache
#
# The index is rebuilt only when the corpus changes. The stamp is (file count,
# newest mtime) — the same cheap test `wiki._stamp()` uses, and enough to catch an
# added, removed or rewritten learning without stat-ing content.
# --------------------------------------------------------------------------- #
_cache: tuple[tuple[int, float], tuple[Learning, ...]] | None = None


def _files() -> list[Path]:
    return sorted(path for directory in SOURCE_DIRS for path in directory.glob("*.md"))


def _stamp(files: list[Path]) -> tuple[int, float]:
    newest = 0.0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    return len(files), newest


def invalidate_cache() -> None:
    """Drop the cached index. Tests, and anything that rewrites the corpus."""
    global _cache
    _cache = None


def build_index() -> list[Learning]:
    """Every learning worth recalling, newest first.

    Ordered by date descending, then id, so the ordering is total: two runs over
    an unchanged corpus produce identical ordinals, and therefore an identical
    prompt. Recent calls come first because recall of a market is more useful when
    it is recent, and because a truncated read loses the oldest rather than a
    random slice.
    """
    global _cache

    files = _files()
    stamp = _stamp(files)
    if _cache is not None and _cache[0] == stamp:
        return list(_cache[1])

    learnings = [row for row in (_learning_from(path) for path in files) if row is not None]
    learnings.sort(key=lambda row: (row.created_at, row.id), reverse=True)

    _cache = (stamp, tuple(learnings))
    return list(learnings)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_index(learnings: list[Learning]) -> str:
    """The index as the model sees it: one numbered line per learning.

    Tags, products and category go on the line because they are free — they are
    already in hand — and they let the model prefer a learning that names the
    product or protocol in play. They are never *required* to match, which is the
    whole reason this is not a tag filter.
    """
    lines = []
    for ordinal, row in enumerate(learnings, start=1):
        facets = [row.category, *row.tags, *row.products]
        suffix = f"  [{' · '.join(f for f in facets if f)}]" if any(facets) else ""
        lines.append(f"{ordinal}. {row.title}{suffix}")
    return "\n".join(lines)


def select(learnings: list[Learning], handles) -> list[Learning]:
    """Resolve the model's chosen ordinals back to learnings.

    Out-of-range and non-numeric handles are dropped, not guessed at, and repeats
    collapse — so a malformed selection returns fewer learnings rather than the
    wrong ones. Output follows the index order, not the order they were named, so
    the synthesis prompt stays newest-first however the model listed them.
    """
    wanted: set[int] = set()
    for handle in handles or []:
        try:
            ordinal = int(str(handle).strip().rstrip("."))
        except (TypeError, ValueError):
            continue
        if 1 <= ordinal <= len(learnings):
            wanted.add(ordinal)

    return [row for ordinal, row in enumerate(learnings, start=1) if ordinal in wanted]


def render_bodies(learnings: list[Learning]) -> str:
    """The chosen learnings in full, formatted as the rest of the vault is.

    Reuses `vault._fmt_learning_for_context` so a learning reads the same here as
    it does in Owl's context and in the call analyser — one format for one thing.
    """
    blocks = []
    for row in learnings:
        try:
            _, body = parse_frontmatter(row.path.read_text(encoding="utf-8"))
        except Exception:
            continue
        blocks.append(format_learning(
            {
                "title": row.title,
                "category": row.category,
                "created_at": row.created_at,
                "tags": list(row.tags),
                "products": list(row.products),
            },
            body,
        ))
    return "\n\n---\n\n".join(blocks)
