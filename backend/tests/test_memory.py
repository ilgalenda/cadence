"""Unit tests for the per-user working-memory substrate (Phase 1)."""
import pytest

from agents.mind import memory, memory_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the memory DB at a throwaway file per test (no shared state)."""
    monkeypatch.setattr(memory_db, "DB_PATH", tmp_path / "memory.db")
    memory_db.init_db()


# --- preferences ---
def test_preferences_upsert_and_overwrite():
    memory.remember_preference("alice", "tone", "consultative")
    memory.remember_preference("alice", "tone", "direct")  # overwrite
    memory.remember_preference("alice", "channel", "email")
    assert memory.get_preferences("alice") == {"tone": "direct", "channel": "email"}


# --- context notes ---
def test_context_notes_newest_first():
    memory.add_context_note("alice", "first")
    memory.add_context_note("alice", "second")
    texts = [n["text"] for n in memory.list_context_notes("alice")]
    assert texts[0] == "second" and texts[1] == "first"


# --- accounts ---
def test_account_upsert_dedupes_by_name_and_keeps_id():
    id1 = memory.upsert_account("alice", "Acme", vertical="finance")
    id2 = memory.upsert_account("alice", "Acme", vertical="defence", status="won")
    assert id1 == id2  # same account, id stable
    accounts = memory.list_accounts("alice", status=None)
    assert len(accounts) == 1
    assert accounts[0]["vertical"] == "defence"  # updated
    assert accounts[0]["status"] == "won"


def test_unknown_vertical_normalises_to_other():
    memory.upsert_account("alice", "Acme", vertical="aerospace")
    assert memory.get_account("alice", "Acme")["vertical"] == "other"


def test_list_accounts_filters_by_status():
    memory.upsert_account("alice", "Live", status="active")
    memory.upsert_account("alice", "Old", status="archived")
    active = [a["name"] for a in memory.list_accounts("alice")]  # default status="active"
    assert active == ["Live"]


# --- per-user isolation ---
def test_per_user_isolation():
    memory.remember_preference("alice", "tone", "direct")
    memory.upsert_account("alice", "Acme")
    assert memory.get_preferences("bob") == {}
    assert memory.list_accounts("bob", status=None) == []


# --- deals ---
def test_deals_link_to_account_and_list():
    acc = memory.upsert_account("alice", "Acme", vertical="finance")
    memory.upsert_deal("alice", "Acme PTP rollout", account_id=acc, stage="proposal", value=50000.0)
    deals = memory.list_deals("alice", account_id=acc)
    assert len(deals) == 1
    assert deals[0]["name"] == "Acme PTP rollout"
    assert deals[0]["stage"] == "proposal"
    assert deals[0]["value"] == 50000.0


# --- vertical cross-referencing ---
def test_topics_for_vertical_ranks_and_excludes():
    a = memory.upsert_account("alice", "AcmeBank", vertical="finance")
    b = memory.upsert_account("alice", "BondCo", vertical="finance")
    memory.record_account_topic("alice", a, "MiFID II timestamping", vertical="finance")
    memory.record_account_topic("alice", b, "MiFID II timestamping", vertical="finance")
    memory.record_account_topic("alice", b, "holdover", vertical="finance")
    # Defence topic must not appear under finance.
    d = memory.upsert_account("alice", "DefCo", vertical="defence")
    memory.record_account_topic("alice", d, "GPS denial", vertical="defence")

    topics = memory.topics_for_vertical("alice", "finance")
    assert topics[0] == "MiFID II timestamping"  # most frequent
    assert "holdover" in topics
    assert "GPS denial" not in topics

    excl = memory.topics_for_vertical("alice", "finance", exclude_account_id=b)
    assert "holdover" not in excl  # holdover only came from the excluded account


# --- render ---
def test_render_empty_is_blank():
    assert memory.render_memory_block("nobody") == ""


def test_render_includes_accounts_prefs_and_crossref():
    memory.remember_preference("alice", "tone", "direct")
    a = memory.upsert_account("alice", "AcmeBank", vertical="finance")
    memory.record_account_topic("alice", a, "MiFID II timestamping", vertical="finance")
    other = memory.upsert_account("alice", "BondCo", vertical="finance")
    memory.record_account_topic("alice", other, "leap-second handling", vertical="finance")

    block = memory.render_memory_block("alice", active_vertical="finance")
    assert "Working memory" in block
    assert "AcmeBank (finance)" in block
    assert "tone=direct" in block
    assert "Cross-reference" in block
    assert "leap-second handling" in block


def test_render_crossref_auto_derives_dominant_vertical():
    a = memory.upsert_account("alice", "AcmeBank", vertical="finance")
    memory.upsert_account("alice", "BondCo", vertical="finance")
    memory.upsert_account("alice", "DefCo", vertical="defence")
    memory.record_account_topic("alice", a, "MiFID II", vertical="finance")
    # No active_vertical passed → dominant vertical (finance) drives the cross-ref.
    block = memory.render_memory_block("alice")
    assert "finance accounts: MiFID II" in block


def test_promote_routes_through_added_knowledge_gate(monkeypatch):
    from agents.shared import vault

    captured: dict = {}
    monkeypatch.setattr(vault, "write_added_knowledge", lambda **kw: captured.update(kw) or "path")
    memory.promote_insight_to_vault(
        "alice", title="T", description="D", content="C", topic="finance"
    )
    assert captured["submitted_by"] == "alice"
    assert captured["content"] == "C"
    assert captured["user_correction"] == "C"  # mapped onto the gate's correction field
    assert captured["suggested_source"] == "owl-memory"


def test_seed_accounts_from_research_briefs(monkeypatch):
    """The forward source: every brief names the account it is about."""
    from agents.mind import memory_seed

    monkeypatch.setattr(
        memory_seed, "_accounts_from_briefs",
        lambda u: ["Acme", "Acme", "BondCo", ""],  # duplicate deduped, blank skipped
    )
    monkeypatch.setattr(memory_seed, "_accounts_from_legacy_campaigns", lambda u: [])

    assert memory_seed.seed_accounts_from_existing("alice") == 2
    names = sorted(a["name"] for a in memory.list_accounts("alice", status=None))
    assert names == ["Acme", "BondCo"]


def test_seed_still_reads_the_retired_campaign_store(monkeypatch):
    """`agents/lead` is gone but its file is not, and it holds real company names
    for anyone who worked leads before the migration."""
    from agents.mind import memory_seed

    monkeypatch.setattr(memory_seed, "_accounts_from_briefs", lambda u: [])
    monkeypatch.setattr(memory_seed, "_accounts_from_legacy_campaigns", lambda u: ["OldCo"])

    assert memory_seed.seed_accounts_from_existing("bob") == 1
    assert [a["name"] for a in memory.list_accounts("bob", status=None)] == ["OldCo"]


def test_the_two_sources_are_deduped_against_each_other(monkeypatch):
    from agents.mind import memory_seed

    monkeypatch.setattr(memory_seed, "_accounts_from_briefs", lambda u: ["Acme"])
    monkeypatch.setattr(memory_seed, "_accounts_from_legacy_campaigns", lambda u: ["acme", "BondCo"])

    assert memory_seed.seed_accounts_from_existing("carol") == 2


def test_one_failing_source_does_not_cost_the_other(monkeypatch):
    """The legacy file may be missing entirely; the briefs must still seed."""
    from agents.mind import memory_seed

    def boom(username):
        raise OSError("campaigns.json is gone")

    monkeypatch.setattr(memory_seed, "_accounts_from_briefs", lambda u: ["Acme"])
    monkeypatch.setattr(memory_seed, "_accounts_from_legacy_campaigns", boom)

    assert memory_seed.seed_accounts_from_existing("dave") == 1


def test_a_missing_legacy_file_reads_as_no_names(monkeypatch, tmp_path):
    """Exercising the real reader, not a stand-in for it."""
    import paths
    from agents.mind import memory_seed

    monkeypatch.setattr(paths, "data_root", lambda: tmp_path)
    assert memory_seed._accounts_from_legacy_campaigns("alice") == []
