"""Acceptance bar for attributed presentation of shared knowledge.

The feature is easy to state and easy to get subtly wrong: **the vault is global,
and this changes only how it is presented.** Everything anybody contributes is in
everybody's context. What attribution buys is that the person who wrote something
is told it is theirs, so a large import does not dissolve into an anonymous corpus
the moment it lands.

Three invariants, in the order they matter:

  1. **Nothing is hidden.** A test that user B sees user A's knowledge in full is
     what proves this is a sharing feature rather than a scoping one. If that ever
     fails, the feature has inverted into the opposite of its purpose.
  2. **The cached prefix stays byte-identical across users.** Per-user text in the
     shared prefix would collapse the Anthropic prompt cache from one prefix for
     everyone to one per user, on every turn, and nothing else in the suite would
     notice.
  3. **A contributor's own work does not fall off the end.** The shared section is
     scored and capped; theirs is carried in the tail when it misses the cut.

Plus the selection fix that makes any of it worth doing — before it, an import
larger than the cap surfaced an arbitrary slice chosen by a random filename.
"""
from __future__ import annotations

import pytest

from agents.mind import contributions_block
from agents.shared import vault


@pytest.fixture
def approved(tmp_path, monkeypatch):
    """An isolated `added/approved/` directory, and a writer for it."""
    pending = tmp_path / "pending"
    approved_dir = tmp_path / "approved"
    for d in (pending, approved_dir):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(vault, "ADDED_PENDING_DIR", pending)
    monkeypatch.setattr(vault, "ADDED_APPROVED_DIR", approved_dir)

    def add(title, *, by, tags=None, body="Some knowledge.", products=None):
        path = vault.write_contribution(
            title=title,
            description=f"{title} description",
            content=body,
            kind="knowledge",
            contributed_by=by,
            tags=tags or [],
            products=products or [],
        )
        entry_id = path.name.split("--", 1)[0]
        return vault.approve_added(entry_id, reviewed_by="sam")

    return add


# ---------------------------------------------------------------------------
# 1. Nothing is hidden — this is a sharing feature
# ---------------------------------------------------------------------------


def test_one_users_contribution_is_in_the_shared_section_for_everyone(approved):
    # No vault entity terms in the body: `_inject_links_and_enrich_meta` rewrites
    # known terms into [[wikilinks]], which would make an exact match brittle.
    approved("Holdover", by="alice", body="Alice wrote this particular sentence.")

    section, _ = vault._build_added_section(None, None, 60)

    assert "Alice wrote this particular sentence." in section
    assert "Holdover" in section


def test_attribution_does_not_filter_the_shared_section(approved):
    """The shared section is identical no matter who is asking — it takes no user."""
    approved("Alice's entry", by="alice")
    approved("Bob's entry", by="bob")

    section, selected = vault._build_added_section(None, None, 60)

    assert "Alice's entry" in section and "Bob's entry" in section
    assert len(selected) == 2


def test_a_non_contributor_still_gets_everything(approved):
    """Carol contributed nothing, so she gets no block — and loses no knowledge."""
    approved("Alice's entry", by="alice")

    section, _ = vault._build_added_section(None, None, 60)
    assert "Alice's entry" in section

    assert contributions_block.render_own_contributions_block("carol") == ""


# ---------------------------------------------------------------------------
# 2. Attribution is presentation, and stays out of the cached prefix
# ---------------------------------------------------------------------------


def test_the_block_names_the_contributor_and_frames_the_work(approved):
    approved("Holdover", by="alice")

    block = contributions_block.render_own_contributions_block("alice", "Alice Smith")

    assert "Alice Smith" in block
    assert "every colleague can see it" in block, "it must not read as private knowledge"


def test_one_users_block_never_carries_anothers_work(approved):
    approved("Alice's entry", by="alice", body="Alice wrote this.")
    approved("Bob's entry", by="bob", body="Bob wrote this.")

    alice = contributions_block.render_own_contributions_block("alice")
    bob = contributions_block.render_own_contributions_block("bob")

    assert "Alice's entry" in alice and "Bob's entry" not in alice
    assert "Bob's entry" in bob and "Alice's entry" not in bob


def test_entries_in_the_shared_section_are_named_not_repeated(approved):
    """The prefix already carries the text; restating it doubles tokens for nothing."""
    approved("Holdover", by="alice", body="A distinctive sentence about oscillators.")

    block = contributions_block.render_own_contributions_block("alice")

    assert "Holdover" in block, "named"
    assert "A distinctive sentence about oscillators." not in block, "not repeated"
    assert "do not repeat it" in block


def test_a_contributor_with_nothing_gets_an_empty_block(approved):
    """Empty rather than a heading with nothing under it — the tail stays clean."""
    assert contributions_block.render_own_contributions_block("nobody") == ""


def test_matching_is_case_insensitive_but_not_fuzzy(approved):
    approved("Alice's entry", by="Alice")

    assert contributions_block.render_own_contributions_block("alice") != ""
    assert contributions_block.render_own_contributions_block("ali") == ""


def test_corrections_attribute_by_submitted_by(approved):
    """Owl-session corrections carry `submitted_by`, bulk imports `contributed_by`."""
    path = vault.write_added_knowledge(
        title="A correction", description="d", content="c", topic="t",
        what_owl_said="x", user_correction="y", submitted_by="alice", session_id="s",
    )
    vault.approve_added(path.name.split("--", 1)[0], reviewed_by="sam")

    assert "A correction" in contributions_block.render_own_contributions_block("alice")


def test_the_session_vault_is_byte_identical_for_two_contributors(approved, monkeypatch):
    """The invariant the prompt cache rests on.

    `persona.system_blocks` marks persona + vault as the cached prefix. If a
    single character of attribution reached it, the Anthropic cache would go from
    one shared prefix to one per user on every turn — a large, silent cost
    increase that no other test in the suite would notice.
    """
    monkeypatch.setattr(vault, "_vault_session_cache", {})
    approved("Alice's entry", by="alice", body="Alice wrote this.")
    approved("Bob's entry", by="bob", body="Bob wrote this.")

    assert vault.load_vault_for_session("alice") == vault.load_vault_for_session("bob")


def test_attribution_rides_the_uncached_tail_not_the_cached_prefix(approved, monkeypatch):
    """Block 0 is the cached prefix; block 1 is the volatile tail."""
    from agents.mind import blocks as mind_blocks

    monkeypatch.setattr(vault, "_vault_session_cache", {})
    approved("Alice's entry", by="alice", body="Alice wrote this.")

    built = mind_blocks.owl_system_blocks(
        "alice",
        contributions_block=contributions_block.render_own_contributions_block("alice", "Alice"),
    )

    assert built[0].get("cache_control"), "block 0 is the cached prefix"
    assert "Alice's own contributions" not in built[0]["text"]
    assert "Alice's own contributions" in built[1]["text"]
    assert "cache_control" not in built[1]


# ---------------------------------------------------------------------------
# 3. A contributor's own work does not fall off the end
# ---------------------------------------------------------------------------


def test_work_that_missed_the_shared_cut_is_carried_in_full(approved):
    """The point of the feature: their own material survives a bad scoring turn."""
    approved("Selected", by="alice", tags=["ptp"], body="This one scores.")
    approved("Unselected", by="alice", tags=[], body="This one does not score.")

    # A budget of one: only the tag-matching entry reaches the shared section.
    block = contributions_block.render_own_contributions_block(
        "alice", tags=["ptp"], max_added=1,
    )

    assert "This one does not score." in block, "carried in full"
    assert "This one scores." not in block, "already in the shared section"


def test_the_carried_set_is_capped(approved, monkeypatch):
    """Uncached tokens are paid on every turn, so this cannot grow without bound."""
    monkeypatch.setattr(contributions_block, "MAX_CARRIED", 2)
    for i in range(6):
        approved(f"Entry {i}", by="alice", body=f"Body number {i}.")

    block = contributions_block.render_own_contributions_block("alice", max_added=0)

    assert sum(f"Body number {i}." in block for i in range(6)) == 2
    assert "further contribution" in block, "what was dropped is stated, not hidden"


def test_rejected_work_is_not_presented_as_contributed(approved):
    """Rejected never reaches `approved/`, so it is nobody's context — including theirs."""
    path = vault.write_contribution(
        title="Rejected idea", description="d", content="c",
        kind="knowledge", contributed_by="alice",
    )
    vault.reject_added(path.name.split("--", 1)[0], reviewed_by="sam")

    assert contributions_block.render_own_contributions_block("alice") == ""


# ---------------------------------------------------------------------------
# 4. The selection fix
# ---------------------------------------------------------------------------


def test_the_shared_section_selects_by_relevance_not_by_filename(approved):
    """Before the fix this sorted by `uuid4().hex[:8]` — a random key.

    Thirty entries against a budget of five: the tagged one must be in, and with a
    random sort its odds were five in thirty.
    """
    for i in range(29):
        approved(f"Filler {i}", by="bob", tags=["unrelated"])
    approved("The relevant one", by="bob", tags=["mifid-ii"], body="What was asked for.")

    section, selected = vault._build_added_section(["mifid-ii"], None, 5)

    assert "What was asked for." in section
    assert len(selected) == 5


def test_products_outweigh_tags_in_selection(approved):
    """`_score_candidate` weights a product match double; the added section inherits it."""
    approved("Tag match", by="bob", tags=["ptp"])
    approved("Product match", by="bob", products=["Open Time Server"])

    _, selected = vault._build_added_section(["ptp"], ["Open Time Server"], 1)

    assert selected[0].title == "Product match"


def test_an_empty_pillar_yields_no_section(approved):
    section, selected = vault._build_added_section(None, None, 60)

    assert section is None and selected == []
