"""The source library — what a knowledge page rests on, and what a call taught.

`vault.py` records provenance, `wiki.py` reads it back verbatim, and this module
judges it: does the call still exist, and may this viewer open it. Keeping the
judgement here is what lets `wiki.py` stay a reader of files — it has no idea
sessions or users exist, and should not acquire one.

Two directions, one subject:

- `sources_for(page, …)` — the calls a knowledge page came from.
- `pages_from_call(call_id)` — everything a call put into the vault.

**Layering:** this module never imports `agents.sales`. Call records arrive as an
argument, because `agents/shared` reaching into an agent would invert the
direction the rest of the codebase is careful about — Learn reads what Sales
produced, and nothing in Sales reads back.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from agents.shared import wiki
from agents.shared.vault import CALLS_DIR, LEAD_DIR, _parse_fm

#: A source whose call exists and belongs to the viewer. Safe to link.
OPEN = "open"
#: A source whose call exists but belongs to a colleague. Named, never linked —
#: the corpus is shared, transcripts are not.
RESTRICTED = "restricted"
#: A source whose call is gone: deleted, or trimmed by the store's session cap.
#: One recorded source in six is already in this state.
MISSING = "missing"


@dataclass(frozen=True)
class CallRecord:
    """One analysed call, reduced to what provenance needs to know about it."""
    call_id: str
    title: str
    owner: str


@dataclass(frozen=True)
class Source:
    """One call a knowledge page came from, judged for one viewer."""
    call_id: str
    title: str
    contributed_by: str
    captured_at: str
    status: str


@dataclass(frozen=True)
class KnowledgePage:
    """One thing a call put into the vault.

    `wiki_slug` is None for a learning, which is readable here but has no wiki
    page — `dynamic/calls/` is deliberately outside the wiki index. That is the
    same idiom `wiki.Link.slug` uses for a link that resolves to nothing.
    """
    key: str
    title: str
    type: str
    summary: str
    wiki_slug: str | None
    contributed_by: str
    captured_at: str


# ---------------------------------------------------------------------------
# A page's sources
# ---------------------------------------------------------------------------

def call_records(sessions: Iterable[dict]) -> dict[str, CallRecord]:
    """Index raw session dicts by call id.

    Takes the sessions rather than reading the store, so this module owes
    nothing to the agent that owns them.
    """
    records: dict[str, CallRecord] = {}
    for session in sessions:
        call_id = str(session.get("id") or "")
        if not call_id:
            continue
        records[call_id] = CallRecord(
            call_id=call_id,
            title=str(session.get("title") or "").strip() or "Untitled call",
            owner=str(session.get("username") or ""),
        )
    return records


def resolve(origin: wiki.Origin, records: Mapping[str, CallRecord], viewer: str) -> Source:
    """One recorded origin, judged against what exists and who is asking.

    The title comes from the live record when there is one, so a call renamed
    after capture reads by its current name, and falls back to the title stored
    at capture, which is all that is left once the call is gone. A source is
    therefore never nameless — and never offers a link it cannot honour.
    """
    record = records.get(origin.call_id)
    if record is None:
        return Source(
            call_id=origin.call_id,
            title=origin.call_title or "A call that is no longer stored",
            contributed_by=origin.contributed_by,
            captured_at=origin.captured_at,
            status=MISSING,
        )

    return Source(
        call_id=origin.call_id,
        title=record.title,
        contributed_by=origin.contributed_by or record.owner,
        captured_at=origin.captured_at,
        status=OPEN if record.owner == viewer else RESTRICTED,
    )


def sources_for(
    page: wiki.Page, records: Mapping[str, CallRecord], viewer: str
) -> list[Source]:
    """A page's sources, newest-recorded first.

    A list although the vault records at most one per page: `first_seen_in` is
    singular, so a term met on a second call cannot currently be observed at all.
    That is worth fixing separately — and the wire shape is a list from the start
    so fixing it stays additive rather than a breaking reshape.
    """
    if page.origin is None:
        return []
    return [resolve(page.origin, records, viewer)]


# ---------------------------------------------------------------------------
# What a call taught — the reverse direction
# ---------------------------------------------------------------------------

#: Learnings live outside the wiki index, so they are read here directly.
_LEARNING_DIRS = (CALLS_DIR, LEAD_DIR)

_cache: tuple[tuple[int, float], dict[str, tuple[KnowledgePage, ...]]] | None = None


def _files() -> list[Path]:
    return sorted(path for directory in _LEARNING_DIRS for path in directory.glob("*.md"))


def _stamp(files: list[Path]) -> tuple[int, float]:
    """(count, newest mtime) — the same cheap corpus test `wiki._stamp` uses."""
    newest = 0.0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    return len(files), newest


def invalidate_cache() -> None:
    """Drop the cached learning index. Tests, and anything that rewrites it."""
    global _cache
    _cache = None


def _learning_page(path: Path) -> tuple[str, KnowledgePage] | None:
    """One learning file as (call id, page), or None if it names no call.

    The call id comes back alongside the page rather than being read again by
    the caller: the file is parsed once, and a learning that records no source
    has no place in an index keyed by source.

    An unreadable file is skipped rather than raised on — one bad file must not
    cost a reader the other five hundred.
    """
    try:
        meta, _ = _parse_fm(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None

    call_id = str(meta.get("source_id") or "").strip().strip('"')
    if not call_id:
        return None

    return call_id, KnowledgePage(
        key=f"learning/{path.stem}",
        title=str(meta.get("title") or "").strip().strip('"') or path.stem,
        type="learning",
        summary=str(meta.get("description") or "").strip().strip('"'),
        wiki_slug=None,
        contributed_by=str(meta.get("contributed_by") or "").strip().strip('"'),
        captured_at=str(meta.get("created_at") or "").strip().strip('"'),
    )


def _learning_index() -> dict[str, tuple[KnowledgePage, ...]]:
    """Learnings bucketed by the call they came from, rebuilt only when it changes."""
    global _cache

    files = _files()
    stamp = _stamp(files)
    if _cache is not None and _cache[0] == stamp:
        return _cache[1]

    buckets: dict[str, list[KnowledgePage]] = {}
    for path in files:
        read = _learning_page(path)
        if read is None:
            continue
        call_id, page = read
        buckets.setdefault(call_id, []).append(page)

    frozen = {call_id: tuple(pages) for call_id, pages in buckets.items()}
    _cache = (stamp, frozen)
    return frozen


def _wiki_pages_by_call() -> dict[str, list[KnowledgePage]]:
    """Wiki-visible pages bucketed by origin, off the corpus cache wiki already keeps."""
    buckets: dict[str, list[KnowledgePage]] = {}
    for node in wiki.index():
        if node.origin is None:
            continue
        buckets.setdefault(node.origin.call_id, []).append(
            KnowledgePage(
                key=node.slug,
                title=node.title,
                type=node.type,
                summary=node.tagline,
                wiki_slug=node.slug,
                contributed_by=node.origin.contributed_by,
                captured_at=node.origin.captured_at,
            )
        )
    return buckets


def pages_from_call(call_id: str) -> list[KnowledgePage]:
    """Everything the vault holds that names this call as its source.

    Two populations in one list — glossary terms, which are wiki pages, and
    learnings, which are not — because "what did this call teach us" is one
    question. Ordered newest first, then by key, so the ordering is total and two
    runs over an unchanged vault agree.
    """
    if not call_id:
        return []

    pages = list(_learning_index().get(call_id, ()))
    pages.extend(_wiki_pages_by_call().get(call_id, []))
    pages.sort(key=lambda page: (page.captured_at, page.key), reverse=True)
    return pages


def counts_by_call() -> dict[str, int]:
    """How many vault pages each call produced, for list rows.

    One pass, so a list of ninety calls costs one index read rather than ninety.
    """
    counts = {call_id: len(pages) for call_id, pages in _learning_index().items()}
    for call_id, pages in _wiki_pages_by_call().items():
        counts[call_id] = counts.get(call_id, 0) + len(pages)
    return counts
