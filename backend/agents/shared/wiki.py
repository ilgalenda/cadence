"""Reading the vault — the query side of the company's knowledge.

`vault.py` assembles the vault into LLM context. This module answers the other
question: *what is in there, and how does one page connect to another* — so a
human can read the same knowledge Owl reads, and walk it.

Three calls make up the surface:

  * `index()`  — every knowledge page, with its type and provenance
  * `search()` — by title, alias, tag or body, ranked
  * `page()`   — one page as structured blocks, with its links and backlinks

Two decisions worth knowing before changing anything here:

**Bodies become blocks, never HTML.** A page is returned as typed blocks whose
text runs are plain strings. The frontend builds DOM and assigns text with
`textContent`, so vault content can never be markup. Parsing lives here, in
Python, next to the corpus it describes.

**A link that resolves to nothing degrades to plain text.** The corpus writes
`[[Grandmaster clock]]` while the page is titled `Grandmaster Clock (GMC)`, so
resolution is forgiving: case-insensitive, over titles, aliases and parenthetical
forms. What it cannot resolve it reports, rather than emitting a link that goes
nowhere — the defect this module exists to end.

The frontmatter and title helpers are imported from `vault.py` under their
private names. Renaming them there would touch 39 call sites in the module every
Owl turn depends on, which is not a trade worth making for a leading underscore;
`scripts/normalise_company_truth.py` already imports them the same way.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from paths import vault_dir

from agents.shared.vault import (
    _build_match_terms as match_terms,
    _extract_wikilinks as extract_wikilinks,
    _parse_fm as parse_frontmatter,
    _slug as slugify,
    _strip_parenthetical as title_forms,
)

# ---------------------------------------------------------------------------
# What counts as a knowledge page
#
# Each directory maps to a type and a pillar. Three stores are deliberately
# absent: `company/knowledge/` configures what the *model* reads (and holds
# Owl's own persona), `dynamic/calls/` and `dynamic/lead/` are work artefacts the
# call library and the paths own, and `added/pending|rejected/` has not passed
# the review gate. Surfacing any of them here would make "knowledge" mean
# several different things at once.
# ---------------------------------------------------------------------------

_SOURCES: tuple[tuple[str, str, str], ...] = (
    # (relative directory, type, pillar)
    ("company/glossary", "glossary", "company"),
    ("company/entities", "entity", "company"),
    ("company/products/hardware", "product", "company"),
    ("company/products/solutions", "solution", "company"),
    ("company/products/industries", "industry", "company"),
    ("company/products/datasheets", "datasheet", "company"),
    ("company/products", "reference", "company"),
    ("company/research", "research", "company"),
    ("dynamic/glossary", "glossary", "dynamic"),
    ("added/approved", "glossary", "added"),
)

KNOWN_TYPES: tuple[str, ...] = (
    "glossary", "entity", "product", "solution", "industry", "datasheet", "reference", "research",
)

# When two pages answer to the same name, this decides which one a `[[link]]`
# reaches. A datasheet sits last because it describes a product that has its own
# page, and the page is what a reader wants.
_TYPE_PRIORITY: dict[str, int] = {name: i for i, name in enumerate(KNOWN_TYPES)}

# Products the company actually sells, as opposed to material describing them.
_PORTFOLIO_TYPES = ("product", "solution")

# Terms, for a glossary reference.
_TERM_TYPES = ("glossary", "entity")

# Pages about a named company — a customer, a partner, an integrator, an account.
# They are knowledge, and they belong in the wiki a human reads. They are kept out
# of the *prompt* references because both quiz prompts instruct the model never to
# name a client, prospect or company: handing it a company profile invites the
# exact violation the prompt forbids. The vault labels them, so this is a filter
# on a real signal rather than a guess at the title.
_ACCOUNT_TAGS = frozenset({"customer", "partner", "integrator", "strategic-account"})


# ---------------------------------------------------------------------------
# Display titles
#
# Product pages store a slug in `title:` (`title: open-time-appliance`), so a
# readable name has to be derived. Token casing handles most of it; the overrides
# are the cases it cannot get right.
# ---------------------------------------------------------------------------

_TOKEN_FORMS: dict[str, str] = {
    "1pps": "1PPS", "5g": "5G", "gmc": "GMC", "gnss": "GNSS", "hft": "HFT",
    "ieee": "IEEE", "ntp": "NTP", "ocp": "OCP", "ocxo": "OCXO", "pnt": "PNT",
    "ptp": "PTP", "stl": "STL", "synce": "SyncE", "taas": "TaaS", "tap": "TAP",
    "utc": "UTC", "vgmc": "vGMC", "wr": "WR",
}

_TITLE_OVERRIDES: dict[str, str] = {
    "ocp-tap-timecard": "OCP-TAP Timecard",
    "ptp-mesh": "PTP² Mesh",
}


def display_title(stem: str) -> str:
    """A readable name for a page whose `title:` is a slug."""
    key = stem.strip().lower()
    if key in _TITLE_OVERRIDES:
        return _TITLE_OVERRIDES[key]
    tokens = [t for t in re.split(r"[-_\s]+", key) if t]
    return " ".join(_TOKEN_FORMS.get(t, t.capitalize()) for t in tokens)


def _is_prose(title: str) -> bool:
    """A title written for a human already, rather than a slug standing in for one."""
    return bool(title) and (" " in title or any(c.isupper() for c in title))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Node:
    """One knowledge page, as it appears in an index or a list of results."""
    slug: str
    title: str
    type: str
    pillar: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    tagline: str
    #: None for company-tier pages, which cite nothing — they are the company's
    #: own truth. Defaulted so existing constructions keep working.
    origin: Origin | None = None
    #: The Cadence username the vault recorded as contributing this page, when it
    #: recorded one. Separate from `origin`, which needs a call id and so is None
    #: for anything imported rather than captured from a conversation. Held here
    #: so the reader can be shown their own work; it grants nothing and hides
    #: nothing — the corpus is readable by everyone either way.
    contributed_by: str = ""


@dataclass(frozen=True)
class Origin:
    """Where a page came from, exactly as the vault recorded it.

    Verbatim and unresolved on purpose. Whether that call still exists, and who
    is allowed to open it, are questions about sessions and viewers that this
    module has no business answering — `agents/shared/sources.py` answers them.
    """
    call_id: str
    #: The call's title at the moment of capture. The call library trims at
    #: `MAX_SESSIONS`, so this outlives the record it names and is the only
    #: thing left to show once the call is gone.
    call_title: str
    contributed_by: str
    captured_at: str


@dataclass(frozen=True)
class Link:
    """A `[[wikilink]]` and where it points. `slug` is None when nothing matched."""
    target: str
    slug: str | None


@dataclass(frozen=True)
class SearchHit:
    node: Node
    rank: int
    matched_on: str


@dataclass(frozen=True)
class Page:
    node: Node
    blocks: tuple[dict, ...]
    links: tuple[Link, ...]
    backlinks: tuple[Node, ...]
    unresolved: tuple[str, ...]

    # A page is mostly its node; forwarding the fields keeps callers from
    # reaching through `.node` for the obvious things.
    @property
    def slug(self) -> str:
        return self.node.slug

    @property
    def title(self) -> str:
        return self.node.title

    @property
    def type(self) -> str:
        return self.node.type

    @property
    def pillar(self) -> str:
        return self.node.pillar

    @property
    def tags(self) -> tuple[str, ...]:
        return self.node.tags

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.node.aliases

    @property
    def tagline(self) -> str:
        return self.node.tagline

    @property
    def origin(self) -> Origin | None:
        return self.node.origin


# ---------------------------------------------------------------------------
# Frontmatter reading
# ---------------------------------------------------------------------------

def _clean_list(raw) -> tuple[str, ...]:
    """Frontmatter lists arrive part-quoted — `["products", "hardware", website]`.

    A tag that kept its quotes would never match a filter or a search.
    """
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        value = str(item).strip().strip('"').strip("'").strip()
        if value:
            out.append(value)
    return tuple(out)


def _node_from_file(path: Path, node_type: str, pillar: str) -> tuple[Node, str]:
    # Pages ingested from the website carry HTML entities (`&ldquo;`, `&amp;`).
    # They are decoded on the way in, because nothing downstream renders HTML —
    # left encoded, a reader would see the entity itself.
    text = html.unescape(path.read_text(encoding="utf-8", errors="replace"))
    meta, body = parse_frontmatter(text)

    declared = str(meta.get("type") or "").strip().lower()
    if pillar == "added" and declared in KNOWN_TYPES:
        node_type = declared

    raw_title = str(meta.get("title") or "").strip().strip('"')
    stem = path.stem
    title = raw_title if _is_prose(raw_title) else display_title(stem)

    # `description` is the fallback because the runtime writers use that key —
    # every dynamic glossary page carries one and no `tagline`, so reading only
    # `tagline` left 182 pages showing blank in the index.
    tagline = str(meta.get("tagline") or meta.get("description") or "").strip().strip('"')

    return (
        Node(
            slug=f"{node_type}/{slugify(stem)}",
            title=title,
            type=node_type,
            pillar=pillar,
            tags=_clean_list(meta.get("tags")),
            aliases=_clean_list(meta.get("aliases")),
            tagline=tagline,
            origin=_origin_from_meta(meta),
            # Bulk contributions carry `contributed_by`, Owl-session corrections
            # `submitted_by`; the vault's two writers name the same thing twice.
            contributed_by=str(
                meta.get("contributed_by") or meta.get("submitted_by") or ""
            ).strip().strip('"'),
        ),
        body,
    )


def _origin_from_meta(meta: dict) -> Origin | None:
    """The provenance a page's frontmatter records, or None if it records none.

    Two keys because two writers: `write_learning` stamps `source_id` and
    `write_glossary_term` stamps `first_seen_in`. They mean the same thing and
    the difference is history, not intent.
    """
    call_id = str(meta.get("source_id") or meta.get("first_seen_in") or "").strip().strip('"')
    if not call_id:
        return None
    return Origin(
        call_id=call_id,
        call_title=str(meta.get("source_title") or "").strip().strip('"'),
        contributed_by=str(meta.get("contributed_by") or "").strip().strip('"'),
        captured_at=str(meta.get("created_at") or "").strip().strip('"'),
    )


# ---------------------------------------------------------------------------
# Inline parsing
# ---------------------------------------------------------------------------

_INLINE_RE = re.compile(
    r"\[\[(?P<link>[^\]]+)\]\]"
    r"|\*\*(?P<strong>[^*]+)\*\*"
    r"|\*(?P<em>[^*]+)\*"
)


def _spans(text: str, resolve) -> list[dict]:
    """Split one run of markdown into typed spans. No HTML is produced anywhere."""
    spans: list[dict] = []
    cursor = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > cursor:
            spans.append({"kind": "text", "text": text[cursor:match.start()]})
        if match.group("link") is not None:
            target, _, label = match.group("link").partition("|")
            target = target.strip()
            spans.append({
                "kind": "link",
                "text": (label.strip() or target),
                "target": target,
                "slug": resolve(target),
            })
        elif match.group("strong") is not None:
            spans.append({"kind": "strong", "text": match.group("strong")})
        else:
            spans.append({"kind": "em", "text": match.group("em")})
        cursor = match.end()
    if cursor < len(text):
        spans.append({"kind": "text", "text": text[cursor:]})
    return spans or [{"kind": "text", "text": ""}]


def _plain(spans) -> str:
    return "".join(s["text"] for s in spans)


# ---------------------------------------------------------------------------
# Block parsing
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(c) for c in cells)


def _parse_blocks(body: str, resolve) -> list[dict]:
    """Body markdown as typed blocks: heading, para, list, table.

    The corpus uses exactly these four. Anything unrecognised becomes a
    paragraph, so no content is ever silently dropped.
    """
    lines = body.splitlines()
    blocks: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            blocks.append({
                "kind": "heading",
                "level": len(heading.group(1)),
                "spans": _spans(heading.group(2).strip(), resolve),
            })
            i += 1
            continue

        if stripped.startswith("|"):
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            blocks.append(_build_table(table_lines, resolve))
            continue

        if _BULLET_RE.match(stripped):
            items: list[list[dict]] = []
            while i < len(lines):
                bullet = _BULLET_RE.match(lines[i].strip())
                if not bullet:
                    break
                items.append(_spans(bullet.group(1).strip(), resolve))
                i += 1
            blocks.append({"kind": "list", "items": items})
            continue

        paragraph: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i].strip()):
            paragraph.append(lines[i].strip())
            i += 1
        blocks.append({"kind": "para", "spans": _spans(" ".join(paragraph), resolve)})

    return blocks


def _is_block_start(stripped: str) -> bool:
    return bool(
        _HEADING_RE.match(stripped) or _BULLET_RE.match(stripped) or stripped.startswith("|")
    )


def _build_table(table_lines: list[str], resolve) -> dict:
    rows = [line for line in table_lines if not _is_separator_row(line)]
    head: list[list[dict]] = []
    body_rows: list[list[list[dict]]] = []

    # A leading separator means the first row was a header; the corpus always
    # writes one, but a table without it should still render.
    has_header = len(table_lines) > 1 and _is_separator_row(table_lines[1])
    if has_header and rows:
        head = [_spans(cell, resolve) for cell in _table_cells(rows[0])]
        rows = rows[1:]
    for row in rows:
        body_rows.append([_spans(cell, resolve) for cell in _table_cells(row)])

    return {"kind": "table", "head": head, "rows": body_rows}


def _drop_redundant_h1(blocks: list[dict], node: Node) -> list[dict]:
    """The corpus repeats the slug as an H1. The page already shows its title."""
    if not blocks or blocks[0]["kind"] != "heading" or blocks[0]["level"] != 1:
        return blocks
    text = _plain(blocks[0]["spans"]).strip().lower()
    if text in {node.title.strip().lower(), node.slug.split("/", 1)[-1]}:
        return blocks[1:]
    return blocks


# ---------------------------------------------------------------------------
# The corpus — built once, cached until the vault changes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Corpus:
    nodes: tuple[Node, ...]
    bodies: dict[str, str]
    resolver: dict[str, str]
    backlinks: dict[str, tuple[str, ...]]
    stamp: tuple[int, float]


_CACHE: dict[Path, _Corpus] = {}


def invalidate_cache() -> None:
    """Drop the cached corpus. Called after a vault write, and by the tests."""
    _CACHE.clear()


def _files(root: Path) -> list[tuple[Path, str, str]]:
    """Every knowledge file, with the type and pillar its location implies.

    `company/products` is listed after its own subdirectories and matches only
    files sitting directly in it, so a datasheet is not also a `reference`.
    """
    found: list[tuple[Path, str, str]] = []
    for rel, node_type, pillar in _SOURCES:
        directory = root / rel
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            found.append((path, node_type, pillar))
    return found


def _stamp(files: list[tuple[Path, str, str]]) -> tuple[int, float]:
    """Cheap staleness check: how many files, and the newest mtime among them."""
    newest = 0.0
    for path, _, _ in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return len(files), newest


def _build_resolver(nodes: tuple[Node, ...]) -> dict[str, str]:
    """Every surface form a `[[link]]` might use, mapped to one slug.

    Where two pages claim the same name, a title beats an alias and the type
    priority breaks the remaining tie — so `[[Open Time Appliance]]` reaches the
    product, not its datasheet.
    """
    claims: dict[str, tuple[int, int, str]] = {}

    def claim(form: str, kind_rank: int, node: Node) -> None:
        key = " ".join(form.lower().split())
        if not key:
            return
        candidate = (kind_rank, _TYPE_PRIORITY.get(node.type, len(KNOWN_TYPES)), node.slug)
        held = claims.get(key)
        if held is None or candidate < held:
            claims[key] = candidate

    for node in nodes:
        stem = node.slug.split("/", 1)[-1]
        for form in title_forms(node.title):
            claim(form, 0, node)
        for alias in node.aliases:
            claim(alias, 1, node)
        claim(stem, 2, node)

    return {key: slug for key, (_, _, slug) in claims.items()}


def _corpus() -> _Corpus:
    root = vault_dir()
    files = _files(root)
    stamp = _stamp(files)

    cached = _CACHE.get(root)
    if cached is not None and cached.stamp == stamp:
        return cached

    nodes: list[Node] = []
    bodies: dict[str, str] = {}
    for path, node_type, pillar in files:
        try:
            node, body = _node_from_file(path, node_type, pillar)
        except OSError:
            continue
        if node.slug in bodies:  # first writer wins, deterministically
            continue
        nodes.append(node)
        bodies[node.slug] = body

    frozen = tuple(nodes)
    resolver = _build_resolver(frozen)

    backlinks: dict[str, list[str]] = {}
    for node in frozen:
        for target in extract_wikilinks(bodies[node.slug]):
            target = target.partition("|")[0].strip()
            slug = resolver.get(" ".join(target.lower().split()))
            if slug and slug != node.slug and node.slug not in backlinks.setdefault(slug, []):
                backlinks[slug].append(node.slug)

    built = _Corpus(
        nodes=frozen,
        bodies=bodies,
        resolver=resolver,
        backlinks={k: tuple(v) for k, v in backlinks.items()},
        stamp=stamp,
    )
    _CACHE[root] = built
    return built


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def index() -> list[Node]:
    """Every knowledge page, ordered by title."""
    return sorted(_corpus().nodes, key=lambda n: n.title.lower())


def resolve_link(target: str) -> str | None:
    """The slug a `[[link]]` points at, or None when the corpus has no such page."""
    return _corpus().resolver.get(" ".join(str(target).lower().split()))


# Rank → what to tell the reader about why this result is here.
_MATCH_REASON = {0: "title", 1: "alias", 2: "title", 3: "alias", 4: "title", 5: "tag", 6: "body"}


def _rank(node: Node, body: str, query: str) -> int | None:
    title = node.title.lower()
    aliases = [a.lower() for a in node.aliases]

    if title == query:
        return 0
    if query in aliases:
        return 1
    if title.startswith(query):
        return 2
    if any(a.startswith(query) for a in aliases):
        return 3
    if query in title:
        return 4
    if query in [t.lower() for t in node.tags]:
        return 5
    if query in body.lower() or query in node.tagline.lower():
        return 6
    return None


def search(query: str, *, limit: int = 50) -> list[SearchHit]:
    """Find pages by title, alias, tag or body, best match first."""
    needle = " ".join(str(query).lower().split())
    if not needle:
        return []

    corpus = _corpus()
    hits: list[SearchHit] = []
    for node in corpus.nodes:
        rank = _rank(node, corpus.bodies.get(node.slug, ""), needle)
        if rank is not None:
            hits.append(SearchHit(node=node, rank=rank, matched_on=_MATCH_REASON[rank]))

    hits.sort(key=lambda h: (h.rank, h.node.title.lower()))
    return hits[:limit]


def page(slug: str) -> Page | None:
    """One page: its blocks, the links out of it, and the links back to it."""
    corpus = _corpus()
    node = next((n for n in corpus.nodes if n.slug == slug), None)
    if node is None:
        return None

    resolve = corpus.resolver
    blocks = _parse_blocks(
        corpus.bodies.get(slug, ""),
        lambda target: resolve.get(" ".join(target.lower().split())),
    )
    blocks = _drop_redundant_h1(blocks, node)

    links: list[Link] = []
    seen: set[str] = set()
    for target in extract_wikilinks(corpus.bodies.get(slug, "")):
        target = target.partition("|")[0].strip()
        if target in seen:
            continue
        seen.add(target)
        links.append(Link(target=target, slug=resolve.get(" ".join(target.lower().split()))))

    by_slug = {n.slug: n for n in corpus.nodes}
    backlinks = tuple(
        by_slug[s] for s in corpus.backlinks.get(slug, ()) if s in by_slug
    )

    return Page(
        node=node,
        blocks=tuple(blocks),
        links=tuple(links),
        backlinks=backlinks,
        unresolved=tuple(link.target for link in links if link.slug is None),
    )


# ---------------------------------------------------------------------------
# Prompt references
#
# These replace the `GLOSSARY` and `PRODUCTS` constants that quiz generation used
# to read. The constants had drifted to a retired portfolio — the quizzes were
# teaching product names the company no longer sells — while the vault carries the
# current one. The line shape is kept, so the prompts are structurally unchanged.
# ---------------------------------------------------------------------------

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")


def _first_sentence(body: str, resolve, *, cap: int = 300) -> str:
    """A term's opening sentence, with vault markup stripped out.

    A whole body per term would bloat a prompt that already carries call
    scenarios; the first sentence is what defines the term.
    """
    for block in _parse_blocks(body, resolve):
        if block["kind"] != "para":
            continue
        text = _plain(block["spans"]).strip()
        if not text:
            continue
        sentence = _SENTENCE_END_RE.split(text, maxsplit=1)[0].strip()
        return sentence[:cap].rstrip()
    return ""


def names_a_company(node: Node) -> bool:
    """Whether this page is about a named company rather than a concept."""
    return bool(_ACCOUNT_TAGS & {tag.lower() for tag in node.tags})


def glossary_reference() -> str:
    """The glossary as prompt reference — one line per term, no company profiles."""
    corpus = _corpus()
    resolve = lambda target: corpus.resolver.get(" ".join(target.lower().split()))  # noqa: E731
    lines = []
    for node in index():
        if node.type not in _TERM_TYPES or names_a_company(node):
            continue
        definition = node.tagline or _first_sentence(corpus.bodies.get(node.slug, ""), resolve)
        if definition:
            lines.append(f"- {node.title}: {definition}")
    return "\n".join(lines)


def products_reference() -> str:
    """The sellable portfolio as prompt reference — one line per product."""
    corpus = _corpus()
    resolve = lambda target: corpus.resolver.get(" ".join(target.lower().split()))  # noqa: E731
    lines = []
    for node in index():
        if node.type not in _PORTFOLIO_TYPES:
            continue
        summary = node.tagline or _first_sentence(corpus.bodies.get(node.slug, ""), resolve)
        lines.append(f"- {node.title} ({node.type}): {summary}".rstrip())
    return "\n".join(lines)
