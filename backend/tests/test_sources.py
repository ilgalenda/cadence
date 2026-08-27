"""Acceptance bar for the source library (`agents.shared.sources`).

What a knowledge page rests on, and what a call taught. The rules that matter
are the ones a reader depends on when the corpus is imperfect — and it is:
measured on the live vault, one recorded source in six points at a call that no
longer exists, and the calls belong to five different people.

  * a source whose call is gone still says what it was, and offers no link
  * a colleague's live call is named as live, not reported as deleted
  * a company-tier page cites nothing, because it is the company's own truth
  * one unreadable file costs a reader that file, not the other five hundred
  * the index rebuilds when the corpus changes and not otherwise
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.shared import sources, wiki


LEARNING = """---
id: ccc1
title: Holdover is the buying trigger
description: A 24h holdover requirement ruled out the incumbent.
type: learning
category: technical
agent: call_analysis
contributed_by: sam
source_id: call-live
source_title: Datacentre operator — holdover
created_at: 2026-07-24T13:57:02+00:00
---

The estate needs 24h holdover.
"""

LEARNING_DEAD_CALL = """---
id: ccc2
title: A learning whose call is gone
description: Still true, no longer checkable.
type: learning
agent: call_analysis
contributed_by: sam
source_id: call-vanished
source_title: The deleted call
created_at: 2026-05-01T09:00:00+00:00
---

Body.
"""

TERM_LIVE = """---
id: ddd1
title: Holdover
description: How long a clock keeps time without a reference.
type: glossary
tags: [holdover]
first_seen_in: call-live
source_title: Datacentre operator — holdover
contributed_by: sam
created_at: 2026-07-24T14:00:00+00:00
---

How long a clock keeps time without a reference.
"""

TERM_COLLEAGUE = """---
id: ddd2
title: Jitter Attenuation
description: Smoothing short-term phase noise.
type: glossary
first_seen_in: call-colleague
source_title: A call martin ran
contributed_by: martin
created_at: 2026-06-02T11:00:00+00:00
---

Smoothing short-term phase noise.
"""

TERM_NO_TITLE = """---
id: ddd3
title: Legacy Term
description: Written before source titles were captured.
type: glossary
first_seen_in: call-vanished
contributed_by: sam
created_at: 2026-02-01T08:00:00+00:00
---

Written before source titles were captured.
"""

COMPANY_TERM = """---
id: eee1
title: White Rabbit
description: Sub-nanosecond Ethernet timing.
type: glossary
tags: [white-rabbit]
---

Sub-nanosecond Ethernet timing.
"""

SESSIONS = [
    {"id": "call-live", "title": "Datacentre operator — holdover (renamed)", "username": "sam"},
    {"id": "call-colleague", "title": "A call martin ran", "username": "martin"},
]


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Path:
    """A miniature vault carrying every provenance state the real one contains."""
    root = tmp_path / "vault"
    files = {
        "company/glossary/white-rabbit.md": COMPANY_TERM,
        "dynamic/glossary/holdover.md": TERM_LIVE,
        "dynamic/glossary/jitter-attenuation.md": TERM_COLLEAGUE,
        "dynamic/glossary/legacy-term.md": TERM_NO_TITLE,
        "dynamic/calls/ccc1--holdover-is-the-buying-trigger.md": LEARNING,
        "dynamic/calls/ccc2--a-learning-whose-call-is-gone.md": LEARNING_DEAD_CALL,
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    monkeypatch.setattr(wiki, "vault_dir", lambda: root)
    monkeypatch.setattr(sources, "_LEARNING_DIRS", (root / "dynamic" / "calls",))
    wiki.invalidate_cache()
    sources.invalidate_cache()
    yield root
    wiki.invalidate_cache()
    sources.invalidate_cache()


@pytest.fixture
def records():
    return sources.call_records(SESSIONS)


def _page(slug: str) -> wiki.Page:
    page = wiki.page(slug)
    assert page is not None, f"fixture vault has no page {slug!r}"
    return page


# --- the three states -------------------------------------------------------

def test_your_own_live_call_is_open_and_reads_by_its_current_name(vault, records):
    [source] = sources.sources_for(_page("glossary/holdover"), records, viewer="sam")
    assert source.status == sources.OPEN
    assert source.title == "Datacentre operator — holdover (renamed)"


def test_a_colleagues_live_call_is_restricted_not_reported_as_deleted(vault, records):
    """The defect a boolean `live` flag would cause on a five-person corpus."""
    [source] = sources.sources_for(_page("glossary/jitter-attenuation"), records, viewer="sam")
    assert source.status == sources.RESTRICTED
    assert source.title == "A call martin ran"
    assert source.contributed_by == "martin"


def test_a_deleted_call_falls_back_to_the_title_captured_at_the_time(vault, records):
    """The 16%-of-rows case: the call is gone, the name it had survives."""
    origin = wiki.Origin(
        call_id="call-vanished",
        call_title="The deleted call",
        contributed_by="sam",
        captured_at="2026-05-01T09:00:00+00:00",
    )
    source = sources.resolve(origin, records, viewer="sam")
    assert source.status == sources.MISSING
    assert source.title == "The deleted call"


def test_a_term_written_before_titles_were_captured_still_names_something(vault, records):
    """182 live terms were written without a title. None may render blank."""
    [source] = sources.sources_for(_page("glossary/legacy-term"), records, viewer="sam")
    assert source.title.strip()


def test_a_company_page_cites_nothing(vault, records):
    assert sources.sources_for(_page("glossary/white-rabbit"), records, viewer="sam") == []


def test_the_owner_of_a_page_is_whoever_contributed_it(vault, records):
    [source] = sources.sources_for(_page("glossary/holdover"), records, viewer="martin")
    assert source.status == sources.RESTRICTED, "sam's call is not martin's to open"


# --- what a call taught -----------------------------------------------------

def test_a_call_reports_both_its_terms_and_its_learnings(vault):
    pages = sources.pages_from_call("call-live")
    assert {page.type for page in pages} == {"glossary", "learning"}


def test_a_learning_has_no_wiki_page_and_says_so(vault):
    [learning] = [p for p in sources.pages_from_call("call-live") if p.type == "learning"]
    assert learning.wiki_slug is None
    assert learning.key.startswith("learning/")


def test_a_term_carries_the_slug_the_wiki_serves_it_under(vault):
    [term] = [p for p in sources.pages_from_call("call-live") if p.type == "glossary"]
    assert term.wiki_slug == "glossary/holdover"
    assert wiki.page(term.wiki_slug) is not None


def test_the_ordering_is_total(vault):
    assert sources.pages_from_call("call-live") == sources.pages_from_call("call-live")


def test_a_call_that_taught_nothing_returns_nothing(vault):
    assert sources.pages_from_call("call-never-happened") == []
    assert sources.pages_from_call("") == []


def test_counts_agree_with_the_pages_themselves(vault):
    counts = sources.counts_by_call()
    assert counts["call-live"] == len(sources.pages_from_call("call-live"))


# --- robustness -------------------------------------------------------------

def test_one_unreadable_learning_does_not_cost_the_others(vault):
    (vault / "dynamic" / "calls" / "broken.md").write_bytes(b"\x80not utf-8 and no frontmatter")
    sources.invalidate_cache()
    assert sources.pages_from_call("call-live")


def test_a_learning_naming_no_call_is_left_out_of_a_source_keyed_index(vault):
    (vault / "dynamic" / "calls" / "orphan.md").write_text(
        "---\ntitle: Orphan\n---\n\nNo source.\n", encoding="utf-8"
    )
    sources.invalidate_cache()
    assert "orphan" not in sources.counts_by_call()
    keys = [page.key for page in sources.pages_from_call("call-live")]
    assert not any("orphan" in key for key in keys)


# --- the cache --------------------------------------------------------------

def test_the_index_rebuilds_when_a_learning_is_added(vault):
    before = len(sources.pages_from_call("call-live"))
    (vault / "dynamic" / "calls" / "ccc3--another.md").write_text(
        LEARNING.replace("ccc1", "ccc3").replace("Holdover is the buying trigger", "Another"),
        encoding="utf-8",
    )
    assert len(sources.pages_from_call("call-live")) == before + 1


def test_invalidate_cache_empties_it(vault):
    sources.pages_from_call("call-live")
    sources.invalidate_cache()
    assert sources._cache is None
