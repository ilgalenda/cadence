"""Acceptance bar for the vault read API (`agents.shared.wiki`).

The vault is the company's knowledge — 106 glossary pages, 24 entities and a
product corpus — and until now only the LLM-context builders could read it. The
UI hard-coded its own stale copies. This module is what lets a human read the
same pages, so the rules that matter are the ones a reader depends on:

  * a term is findable by its alias, not only its title
  * `[[links]]` resolve across the corpus's inconsistent casing, and a link that
    resolves to nothing degrades to plain text rather than a dead link
  * a product page's display name is derivable, because the corpus stores slugs
    in `title:`
  * a body becomes structured blocks, never HTML — the frontend sets text with
    `textContent`, so there is no injection surface to sanitise

The fixture vault is the contract. The tests at the end run against the real
corpus as a canary and skip when it is absent, because a machine without
`DATA_ROOT` populated should still be able to run the suite.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.shared import wiki


# ---------------------------------------------------------------------------
# Fixture vault
# ---------------------------------------------------------------------------

GLOSSARY_WR = """---
id: aaa1
title: 10 Gigabit White Rabbit
type: glossary
aliases: [10G White Rabbit, 10GbE WR]
tags: [white-rabbit, 10gbe, hft]
---

An emerging extension of the [[White Rabbit Ecosystem]] to 10 Gigabit Ethernet.

**Sales note:** confirm the hardware is 10G-capable.

**Related products:** [[Open Time Node WR]], [[Nonexistent Thing]]
"""

GLOSSARY_HOLDOVER = """---
id: aaa2
title: Holdover
type: glossary
aliases: []
tags: [holdover, ocxo]
---

How long a clock keeps time after losing its reference. Rubidium beats quartz.
"""

ENTITY_1PPS = """---
id: bbb1
title: 1PPS (One Pulse Per Second)
type: entity
entity_type: protocol
aliases: []
tags: [1pps]
---

A precise hardware electrical pulse used to discipline local oscillators.
"""

PRODUCT_APPLIANCE = """---
title: open-time-appliance
slug: open-time-appliance
tagline: Grandmaster clock platform — resilient PNT in a rack-ready chassis.
category: hardware
tags: ["products", "hardware", grandmaster, holdover]
tier: company
locked: True
---

# open-time-appliance

*[[Grandmaster clock]] platform — resilient [[PNT]] in a rack-ready chassis.*

The flagship grandmaster. Three oscillator grades, from quartz up to [[Rubidium]].

## Highlights

- **<120 ns** — Rb Black+ 24 h
- **3 / 1RU** — Density

## Specifications

| Spec | Value |
| --- | --- |
| Frequency | 10 MHz |
| [[Holdover]] | <500 ns / 24 h |
"""

DATASHEET_APPLIANCE = """---
title: open-time-appliance
slug: open-time-appliance
tagline: Datasheet — Open Time Appliance.
category: datasheets
tags: [datasheet]
---

# open-time-appliance

Ordering codes and mechanical drawings.
"""

SOLUTION_VGMC = """---
title: vgmc
slug: vgmc
tagline: Serve hundreds of isolated PTP feeds from one server.
category: solutions
tags: [vgmc, ptp]
---

Turns a Linux server into a virtual grandmaster.
"""

SOLUTION_PTP_MESH = """---
title: ptp-mesh
slug: ptp-mesh
tagline: Mesh-based PTP with no single point of failure.
category: solutions
tags: [ptp, resilience]
---

Resilient mesh synchronisation using clock quorum techniques.
"""

ENTITY_ACCOUNT = """---
id: bbb2
title: Northwind Integrators (Partner Profile)
type: glossary
aliases: []
tags: [integrator, partner, telecom]
---

A regional integrator running turnkey timing projects.
"""

WEB_INGESTED = """---
title: fleet-insight
slug: fleet-insight
tagline: Turn months of clock data into the answer to &ldquo;what happened last Tuesday?&rdquo;
category: solutions
tags: [monitoring]
---

Clock history, searchable — Frequency &amp; phase over time.
"""

DYNAMIC_TERM = """---
id: ccc1
title: Jitter Attenuation
type: glossary
aliases: []
tags: [jitter]
---

Filtering network noise out of every timestamp. Learned from a call.
"""

ADDED_TERM = """---
id: ddd1
title: Approved Correction
type: glossary
aliases: []
tags: [correction]
---

A user correction that passed the review gate.
"""


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Path:
    """A miniature vault with the same layout and the same messiness as the real one."""
    root = tmp_path / "vault"
    files = {
        "company/glossary/10-gigabit-white-rabbit.md": GLOSSARY_WR,
        "company/glossary/holdover.md": GLOSSARY_HOLDOVER,
        "company/entities/1pps-one-pulse-per-second.md": ENTITY_1PPS,
        "company/entities/northwind-integrators.md": ENTITY_ACCOUNT,
        "company/products/solutions/fleet-insight.md": WEB_INGESTED,
        "company/products/hardware/open-time-appliance.md": PRODUCT_APPLIANCE,
        "company/products/datasheets/open-time-appliance.md": DATASHEET_APPLIANCE,
        "company/products/solutions/vgmc.md": SOLUTION_VGMC,
        "company/products/solutions/ptp-mesh.md": SOLUTION_PTP_MESH,
        "dynamic/glossary/jitter-attenuation.md": DYNAMIC_TERM,
        "added/approved/approved-correction.md": ADDED_TERM,
        # Deliberately present and deliberately never indexed.
        "company/knowledge/Persona.md": "---\ntitle: Persona\n---\n\nOwl's own persona.\n",
        "dynamic/calls/some-call.md": "---\ntitle: A call\n---\n\nCall notes.\n",
        "added/pending/not-yet.md": "---\ntitle: Pending\n---\n\nAwaiting review.\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    monkeypatch.setattr(wiki, "vault_dir", lambda: root)
    wiki.invalidate_cache()
    yield root
    wiki.invalidate_cache()


def slugs(nodes) -> set[str]:
    return {n.slug for n in nodes}


# ---------------------------------------------------------------------------
# index — what is knowledge, and what is not
# ---------------------------------------------------------------------------

def test_index_covers_every_knowledge_pillar(vault):
    found = slugs(wiki.index())
    assert "glossary/10-gigabit-white-rabbit" in found      # company truth
    assert "glossary/jitter-attenuation" in found           # grown from calls
    assert "glossary/approved-correction" in found          # added + approved
    assert "entity/1pps-one-pulse-per-second" in found
    assert "product/open-time-appliance" in found
    assert "solution/vgmc" in found


def test_index_excludes_what_is_not_human_knowledge(vault):
    """Owl's persona, raw call notes and the review queue are not wiki pages.

    Each is excluded for its own reason: the persona configures the model, call
    notes are the library's job, and pending entries have not passed review.
    """
    found = slugs(wiki.index())
    assert not any(s.startswith("knowledge/") for s in found)
    assert not any("some-call" in s for s in found)
    assert not any("not-yet" in s for s in found)


def test_slug_is_namespaced_by_type_so_collisions_survive(vault):
    """`open-time-appliance.md` exists in both hardware/ and datasheets/.

    Namespacing is not cosmetic — without it one page silently shadows the other.
    """
    found = slugs(wiki.index())
    assert "product/open-time-appliance" in found
    assert "datasheet/open-time-appliance" in found


def test_pillar_is_recorded_so_provenance_can_be_shown(vault):
    by_slug = {n.slug: n for n in wiki.index()}
    assert by_slug["glossary/10-gigabit-white-rabbit"].pillar == "company"
    assert by_slug["glossary/jitter-attenuation"].pillar == "dynamic"
    assert by_slug["glossary/approved-correction"].pillar == "added"


def test_tags_are_unquoted(vault):
    """The corpus writes `tags: ["products", "hardware", grandmaster]` — mixed.

    A tag carrying its quotes would never match a filter or a search.
    """
    by_slug = {n.slug: n for n in wiki.index()}
    assert "products" in by_slug["product/open-time-appliance"].tags
    assert "hardware" in by_slug["product/open-time-appliance"].tags
    assert not any('"' in t for t in by_slug["product/open-time-appliance"].tags)


# ---------------------------------------------------------------------------
# display titles — the corpus stores slugs in `title:`
# ---------------------------------------------------------------------------

def test_prose_titles_are_left_alone(vault):
    by_slug = {n.slug: n for n in wiki.index()}
    assert by_slug["glossary/10-gigabit-white-rabbit"].title == "10 Gigabit White Rabbit"
    assert by_slug["entity/1pps-one-pulse-per-second"].title == "1PPS (One Pulse Per Second)"


def test_slug_titles_are_resolved_to_names(vault):
    by_slug = {n.slug: n for n in wiki.index()}
    assert by_slug["product/open-time-appliance"].title == "Open Time Appliance"


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("open-time-appliance", "Open Time Appliance"),
        ("open-time-node-wr", "Open Time Node WR"),
        ("ocp-tap-timecard", "OCP-TAP Timecard"),
        ("utc-verification", "UTC Verification"),
        ("ptp-mesh", "PTP² Mesh"),
        ("vgmc", "vGMC"),
        ("acme-app", "Acme App"),
        ("clock-ensemble", "Clock Ensemble"),
        ("fleet-insight", "Fleet Insight"),
    ],
)
def test_display_title_rules(stem, expected):
    """Title-casing alone gets the acronyms wrong; these are the cases that matter."""
    assert wiki.display_title(stem) == expected


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def test_alias_finds_the_page(vault):
    """"10GbE WR" appears nowhere in the title — only in `aliases`."""
    hits = wiki.search("10GbE WR")
    assert hits, "alias search returned nothing"
    assert hits[0].node.slug == "glossary/10-gigabit-white-rabbit"


def test_search_is_case_insensitive(vault):
    assert wiki.search("holdover")[0].node.slug == "glossary/holdover"
    assert wiki.search("HOLDOVER")[0].node.slug == "glossary/holdover"


def test_exact_title_outranks_tag_and_body(vault):
    """Searching "holdover" must land on the term itself, not on pages mentioning it.

    The Open Time Appliance carries `holdover` as a tag and in its body; the
    glossary page *is* the answer.
    """
    ranked = [h.node.slug for h in wiki.search("holdover")]
    assert ranked[0] == "glossary/holdover"
    assert "product/open-time-appliance" in ranked
    assert ranked.index("glossary/holdover") < ranked.index("product/open-time-appliance")


def test_body_match_is_found_but_ranked_last(vault):
    ranked = [h.node.slug for h in wiki.search("mechanical drawings")]
    assert ranked == ["datasheet/open-time-appliance"]


def test_search_reports_what_matched(vault):
    """The UI says *why* a result is there, so the match reason is part of the contract."""
    assert wiki.search("10GbE WR")[0].matched_on == "alias"
    assert wiki.search("Holdover")[0].matched_on == "title"


def test_empty_query_returns_nothing(vault):
    assert wiki.search("") == []
    assert wiki.search("   ") == []


def test_search_respects_limit(vault):
    assert len(wiki.search("a", limit=2)) <= 2


# ---------------------------------------------------------------------------
# page — links, blocks, backlinks
# ---------------------------------------------------------------------------

def test_unknown_slug_returns_none(vault):
    assert wiki.page("glossary/does-not-exist") is None


def test_links_resolve_despite_corpus_casing(vault):
    """Bodies write `[[Grandmaster clock]]` and `[[Open TimeCard]]`; pages are titled
    otherwise. Resolution is case-insensitive and tolerates a parenthetical."""
    page = wiki.page("glossary/10-gigabit-white-rabbit")
    resolved = {link.target: link.slug for link in page.links}
    assert resolved["White Rabbit Ecosystem"] is None  # no such page in the fixture
    assert resolved["Open Time Node WR"] is None

    appliance = wiki.page("product/open-time-appliance")
    by_target = {link.target: link.slug for link in appliance.links}
    assert by_target["Holdover"] == "glossary/holdover"

    # Cased against a *multi-word* title and a *cased alias* — neither of which a
    # page's lowercase filename can stand in for, so this pins the rule itself
    # rather than passing by accident.
    assert wiki.resolve_link("10 GIGABIT white rabbit") == "glossary/10-gigabit-white-rabbit"
    assert wiki.resolve_link("10gbe wr") == "glossary/10-gigabit-white-rabbit"


def test_link_resolution_tolerates_parenthetical_titles(vault):
    """`[[1PPS]]` must reach the page titled "1PPS (One Pulse Per Second)"."""
    assert wiki.resolve_link("1PPS") == "entity/1pps-one-pulse-per-second"
    assert wiki.resolve_link("One Pulse Per Second") == "entity/1pps-one-pulse-per-second"
    assert wiki.resolve_link("1pps") == "entity/1pps-one-pulse-per-second"


def test_link_prefers_the_product_over_its_datasheet(vault):
    """Both pages answer to the same name; the product page is what a reader wants."""
    assert wiki.resolve_link("Open Time Appliance") == "product/open-time-appliance"


def test_unresolved_links_are_reported_not_dropped(vault):
    """A dead link is the defect this replaces — so it is surfaced, and the span
    carries no slug, which is how the renderer knows to emit plain text."""
    page = wiki.page("glossary/10-gigabit-white-rabbit")
    assert "Nonexistent Thing" in page.unresolved

    spans = [s for block in page.blocks for s in block.get("spans", [])]
    dead = [s for s in spans if s["kind"] == "link" and s["text"] == "Nonexistent Thing"]
    assert dead and dead[0]["slug"] is None


def test_backlinks_point_home(vault):
    """The graph is walkable in both directions — that is the point of a wiki."""
    page = wiki.page("glossary/holdover")
    assert "product/open-time-appliance" in {b.slug for b in page.backlinks}


def test_blocks_carry_structure_not_html(vault):
    page = wiki.page("product/open-time-appliance")
    kinds = [b["kind"] for b in page.blocks]
    assert "heading" in kinds
    assert "para" in kinds
    assert "list" in kinds
    assert "table" in kinds

    rendered = repr(page.blocks)
    assert "<" not in rendered.replace("<120", "").replace("<500", ""), "no markup in blocks"


def test_table_keeps_its_head_and_cells(vault):
    page = wiki.page("product/open-time-appliance")
    table = next(b for b in page.blocks if b["kind"] == "table")
    head = ["".join(s["text"] for s in cell) for cell in table["head"]]
    assert head == ["Spec", "Value"]
    first = ["".join(s["text"] for s in cell) for cell in table["rows"][0]]
    assert first == ["Frequency", "10 MHz"]
    # A wikilink inside a cell still resolves.
    linked = [s for row in table["rows"] for cell in row for s in cell if s["kind"] == "link"]
    assert any(s["slug"] == "glossary/holdover" for s in linked)


def test_list_items_keep_emphasis(vault):
    page = wiki.page("product/open-time-appliance")
    items = next(b for b in page.blocks if b["kind"] == "list")["items"]
    first = items[0]
    assert first[0]["kind"] == "strong"
    assert first[0]["text"] == "<120 ns"


def test_redundant_h1_is_dropped(vault):
    """The corpus repeats the slug as an H1; the page already shows its title."""
    page = wiki.page("product/open-time-appliance")
    assert page.blocks[0]["kind"] != "heading" or page.blocks[0]["level"] != 1


def test_heading_levels_survive(vault):
    page = wiki.page("product/open-time-appliance")
    levels = {b["level"] for b in page.blocks if b["kind"] == "heading"}
    assert 2 in levels


# ---------------------------------------------------------------------------
# prompt references — the fix for quizzes teaching retired product names
# ---------------------------------------------------------------------------

def test_products_reference_lists_the_sellable_portfolio(vault):
    text = wiki.products_reference()
    assert "Open Time Appliance" in text
    assert "vGMC" in text
    # Datasheets are supporting material, not products in their own right.
    assert "Ordering codes" not in text


def test_products_reference_carries_no_retired_names(vault):
    text = wiki.products_reference()
    for retired in ("Clock Sync Software", "Clock Quorum", "White Rabbit Ecosystem"):
        assert retired not in text


def test_glossary_reference_is_one_line_per_term(vault):
    text = wiki.glossary_reference()
    lines = [line for line in text.splitlines() if line.strip()]
    assert all(line.startswith("- ") for line in lines)
    assert any(line.startswith("- Holdover:") for line in lines)
    # A term's first sentence is enough for a prompt; whole bodies would bloat it.
    assert all(len(line) < 400 for line in lines)


def test_glossary_reference_includes_terms_grown_from_calls(vault):
    assert "Jitter Attenuation" in wiki.glossary_reference()


def test_prompt_references_never_name_a_company(vault):
    """Both quiz prompts forbid naming a client, prospect or company.

    Company profiles are legitimate wiki pages — a human should read them — but
    handing one to a prompt that must not name companies invites the exact
    violation it forbids.
    """
    assert "Northwind" not in wiki.glossary_reference()
    assert "Northwind" not in wiki.products_reference()

    # Still a first-class page for a reader, though.
    assert "entity/northwind-integrators" in slugs(wiki.index())


def test_html_entities_are_decoded(vault):
    """Pages ingested from the website carry `&ldquo;` and `&amp;` as literal text."""
    by_slug = {n.slug: n for n in wiki.index()}
    tagline = by_slug["solution/fleet-insight"].tagline
    assert "&ldquo;" not in tagline and "&rdquo;" not in tagline
    assert "“what happened last Tuesday?”" in tagline

    page = wiki.page("solution/fleet-insight")
    body_text = "".join(
        span["text"] for block in page.blocks for span in block.get("spans", [])
    )
    assert "&amp;" not in body_text
    assert "Frequency & phase" in body_text


def test_references_carry_no_wikilink_syntax(vault):
    """A prompt should read as prose, not as vault markup."""
    for text in (wiki.glossary_reference(), wiki.products_reference()):
        assert "[[" not in text and "]]" not in text


# ---------------------------------------------------------------------------
# caching
# ---------------------------------------------------------------------------

def test_edited_page_is_picked_up(vault):
    assert wiki.page("glossary/holdover") is not None
    (vault / "company/glossary/new-term.md").write_text(
        "---\ntitle: Brand New Term\ntype: glossary\naliases: []\ntags: []\n---\n\nJust added.\n",
        encoding="utf-8",
    )
    wiki.invalidate_cache()
    assert "glossary/new-term" in slugs(wiki.index())


# ---------------------------------------------------------------------------
# Canary: the real corpus. Skipped when the machine has no vault populated.
# ---------------------------------------------------------------------------

REPO_VAULT = Path(__file__).resolve().parent.parent / "vault"

# Deliberately the repo's own vault, not `paths.vault_dir()`. The route-test
# modules point DATA_ROOT at a temp directory process-wide, so a canary keyed to
# the environment would quietly skip in a full-suite run and only pass when this
# file is run alone — the least useful possible behaviour for a canary.
real_corpus = pytest.mark.skipif(
    not (REPO_VAULT / "company" / "glossary").is_dir()
    or not any((REPO_VAULT / "company" / "glossary").glob("*.md")),
    reason="no corpus checked into backend/vault",
)


@pytest.fixture
def corpus(monkeypatch):
    monkeypatch.setattr(wiki, "vault_dir", lambda: REPO_VAULT)
    wiki.invalidate_cache()
    yield REPO_VAULT
    wiki.invalidate_cache()


@real_corpus
def test_real_corpus_indexes_broadly(corpus):
    nodes = wiki.index()
    types = {n.type for n in nodes}
    assert len(nodes) > 100
    assert {"glossary", "entity", "product"} <= types


@real_corpus
def test_real_corpus_products_are_current(corpus):
    text = wiki.products_reference()
    assert "Open Time Appliance" in text
    for retired in ("Clock Sync Software", "Clock Quorum"):
        assert retired not in text, f"{retired} is still being taught"


@real_corpus
def test_real_corpus_link_health_is_reported(corpus):
    """Not an assertion that the corpus is perfect — a measurement that it can be
    measured. Unresolved links are surfaced so they can be repaired."""
    total = unresolved = 0
    for node in wiki.index():
        page = wiki.page(node.slug)
        if page is None:
            continue
        total += len(page.links)
        unresolved += len(page.unresolved)
    assert total > 0
    assert unresolved <= total
