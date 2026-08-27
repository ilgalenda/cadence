"""Unit tests for Owl's organisation layer — projects, folders, placement, search.

The behaviours worth locking are the ones that protect a user's work: deleting a
container must never destroy conversations, ownership must be enforced at the
data layer, and a folder must never be able to contain itself.
"""
import pytest

from agents.owl import db, projects, storage
from agents.owl.projects import OrganisationError


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the Owl DB at a throwaway file per test (no shared state)."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "owl.db")
    db.init_db()


def _conversation(conv_id: str, username: str = "alice", *, project_id=None) -> None:
    """Create a conversation the way the chat route does — user turn first."""
    storage.append_user_turn(
        conv_id, username, f"question in {conv_id}",
        title=f"Conv {conv_id}", model_used="sonnet", topics=[], project_id=project_id,
    )


# ── Migration ───────────────────────────────────────────────────────────────

def test_migration_is_idempotent_and_preserves_rows():
    _conversation("c1")
    db.init_db()  # run the additive migration a second time
    db.init_db()
    session = storage.get_conversation("c1", "alice")
    assert session is not None
    assert session["project_id"] is None
    assert session["pinned"] is False
    assert session["archived"] is False


# ── Projects ────────────────────────────────────────────────────────────────

def test_create_and_list_projects_in_order():
    projects.create_project("alice", "Northgate")
    projects.create_project("alice", "Toronto")
    names = [p["name"] for p in projects.list_projects("alice")]
    assert names == ["Northgate", "Toronto"]


def test_projects_are_scoped_to_their_owner():
    mine = projects.create_project("alice", "Northgate")
    projects.create_project("bob", "Bob's")
    assert [p["id"] for p in projects.list_projects("alice")] == [mine["id"]]
    assert projects.get_project(mine["id"], "bob") is None


def test_create_project_rejects_a_blank_name():
    with pytest.raises(OrganisationError):
        projects.create_project("alice", "   ")


def test_update_project_name_and_instructions():
    p = projects.create_project("alice", "Northgate")
    updated = projects.update_project(
        p["id"], "alice", name="Northgate Nordics", instructions="Always lead with compliance.",
    )
    assert updated["name"] == "Northgate Nordics"
    assert updated["instructions"] == "Always lead with compliance."


def test_update_project_refuses_an_unowned_project():
    p = projects.create_project("alice", "Northgate")
    with pytest.raises(OrganisationError, match="not found"):
        projects.update_project(p["id"], "bob", name="Hijacked")


def test_archived_projects_are_hidden_unless_asked_for():
    p = projects.create_project("alice", "Northgate")
    projects.set_project_archived(p["id"], "alice", True)
    assert projects.list_projects("alice") == []
    assert len(projects.list_projects("alice", include_archived=True)) == 1


def test_project_conversation_count_excludes_archived_and_deleted():
    p = projects.create_project("alice", "Northgate")
    _conversation("c1", project_id=p["id"])
    _conversation("c2", project_id=p["id"])
    _conversation("c3", project_id=p["id"])
    storage.set_archived("c2", "alice", True)
    storage.delete_conversation("c3", "alice")
    assert projects.list_projects("alice")[0]["conversation_count"] == 1


def test_reorder_puts_unlisted_projects_behind_the_listed_ones():
    a = projects.create_project("alice", "A")
    b = projects.create_project("alice", "B")
    c = projects.create_project("alice", "C")
    projects.reorder_projects("alice", [c["id"], a["id"]])
    assert [p["name"] for p in projects.list_projects("alice")] == ["C", "A", "B"]
    assert [p["id"] for p in projects.list_projects("alice")][2] == b["id"]


def test_reorder_rejects_a_project_the_user_does_not_own():
    theirs = projects.create_project("bob", "Bob's")
    with pytest.raises(OrganisationError, match="unknown project"):
        projects.reorder_projects("alice", [theirs["id"]])


# ── Deleting a container never destroys conversations ───────────────────────

def test_deleting_a_project_unfiles_its_conversations_rather_than_deleting_them():
    p = projects.create_project("alice", "Northgate")
    f = projects.create_folder(p["id"], "alice", "Discovery")
    _conversation("c1", project_id=p["id"])
    storage.move_conversation("c1", "alice", p["id"], f["id"])

    released = projects.delete_project(p["id"], "alice")

    assert released == 1
    session = storage.get_conversation("c1", "alice")
    assert session is not None, "the conversation must survive its project"
    assert session["project_id"] is None
    assert session["folder_id"] is None
    assert projects.list_projects("alice") == []


def test_deleting_a_folder_lifts_conversations_to_the_project_root():
    p = projects.create_project("alice", "Northgate")
    parent = projects.create_folder(p["id"], "alice", "Discovery")
    child = projects.create_folder(p["id"], "alice", "Calls", parent_id=parent["id"])
    _conversation("c1", project_id=p["id"])
    storage.move_conversation("c1", "alice", p["id"], child["id"])

    released = projects.delete_folder(parent["id"], "alice")

    assert released == 1
    session = storage.get_conversation("c1", "alice")
    assert session["project_id"] == p["id"], "still in the project"
    assert session["folder_id"] is None, "lifted to the project root"
    assert projects.list_folders(p["id"], "alice") == []


# ── Folders ─────────────────────────────────────────────────────────────────

def test_folder_tree_nests_children_under_their_parent():
    p = projects.create_project("alice", "Northgate")
    parent = projects.create_folder(p["id"], "alice", "Discovery")
    child = projects.create_folder(p["id"], "alice", "Calls", parent_id=parent["id"])

    tree = projects.folder_tree(p["id"], "alice")

    assert len(tree) == 1
    assert tree[0]["id"] == parent["id"]
    assert [c["id"] for c in tree[0]["children"]] == [child["id"]]


def test_folder_cannot_be_created_under_a_parent_in_another_project():
    p1 = projects.create_project("alice", "One")
    p2 = projects.create_project("alice", "Two")
    outsider = projects.create_folder(p2["id"], "alice", "Elsewhere")
    with pytest.raises(OrganisationError, match="different project"):
        projects.create_folder(p1["id"], "alice", "Nope", parent_id=outsider["id"])


def test_folder_cannot_be_moved_into_itself():
    p = projects.create_project("alice", "Northgate")
    f = projects.create_folder(p["id"], "alice", "Discovery")
    with pytest.raises(OrganisationError, match="cannot contain itself"):
        projects.move_folder(f["id"], "alice", f["id"])


def test_folder_cannot_be_moved_into_its_own_descendant():
    p = projects.create_project("alice", "Northgate")
    grandparent = projects.create_folder(p["id"], "alice", "A")
    parent = projects.create_folder(p["id"], "alice", "B", parent_id=grandparent["id"])
    child = projects.create_folder(p["id"], "alice", "C", parent_id=parent["id"])
    with pytest.raises(OrganisationError, match="own descendant"):
        projects.move_folder(grandparent["id"], "alice", child["id"])


def test_folder_move_to_root_is_allowed():
    p = projects.create_project("alice", "Northgate")
    parent = projects.create_folder(p["id"], "alice", "A")
    child = projects.create_folder(p["id"], "alice", "B", parent_id=parent["id"])
    moved = projects.move_folder(child["id"], "alice", None)
    assert moved["parent_id"] is None


# ── Placement ───────────────────────────────────────────────────────────────

def test_assert_destination_rejects_a_folder_without_its_project():
    p = projects.create_project("alice", "Northgate")
    f = projects.create_folder(p["id"], "alice", "Discovery")
    with pytest.raises(OrganisationError, match="requires its project"):
        projects.assert_destination("alice", None, f["id"])


def test_assert_destination_rejects_a_folder_from_a_different_project():
    p1 = projects.create_project("alice", "One")
    p2 = projects.create_project("alice", "Two")
    f2 = projects.create_folder(p2["id"], "alice", "Elsewhere")
    with pytest.raises(OrganisationError, match="does not belong"):
        projects.assert_destination("alice", p1["id"], f2["id"])


def test_unfiled_filter_returns_only_conversations_with_no_project():
    p = projects.create_project("alice", "Northgate")
    _conversation("filed", project_id=p["id"])
    _conversation("loose")
    unfiled = storage.list_conversations("alice", project_id=None, folder_id=None)
    assert [c["id"] for c in unfiled] == ["loose"]


def test_project_filter_returns_the_whole_project_including_its_folders():
    p = projects.create_project("alice", "Northgate")
    f = projects.create_folder(p["id"], "alice", "Discovery")
    _conversation("root", project_id=p["id"])
    _conversation("nested", project_id=p["id"])
    storage.move_conversation("nested", "alice", p["id"], f["id"])
    ids = {c["id"] for c in storage.list_conversations("alice", project_id=p["id"])}
    assert ids == {"root", "nested"}


def test_folder_filter_narrows_to_that_folder():
    p = projects.create_project("alice", "Northgate")
    f = projects.create_folder(p["id"], "alice", "Discovery")
    _conversation("root", project_id=p["id"])
    _conversation("nested", project_id=p["id"])
    storage.move_conversation("nested", "alice", p["id"], f["id"])
    ids = [c["id"] for c in storage.list_conversations("alice", folder_id=f["id"])]
    assert ids == ["nested"]


def test_moving_a_conversation_you_do_not_own_changes_nothing():
    p = projects.create_project("alice", "Northgate")
    _conversation("c1", "alice")
    assert storage.move_conversation("c1", "bob", p["id"], None) is False
    assert storage.get_conversation("c1", "alice")["project_id"] is None


# ── Pinning & archiving ─────────────────────────────────────────────────────

def test_pinned_conversations_sort_above_newer_unpinned_ones():
    _conversation("old")
    _conversation("new")
    storage.set_pinned("old", "alice", True)
    assert [c["id"] for c in storage.list_conversations("alice")][0] == "old"


def test_archived_conversations_are_hidden_but_restorable():
    _conversation("c1")
    storage.set_archived("c1", "alice", True)
    assert storage.list_conversations("alice") == []
    assert len(storage.list_conversations("alice", include_archived=True)) == 1

    storage.set_archived("c1", "alice", False)
    assert len(storage.list_conversations("alice")) == 1
    assert storage.get_conversation("c1", "alice")["messages"], "messages survive archiving"


# ── Search ──────────────────────────────────────────────────────────────────

def test_search_finds_the_message_and_returns_a_snippet():
    _conversation("c1")
    storage.append_assistant_turn(
        "c1", "alice",
        "A grandmaster in holdover runs on its own oscillator until it drifts out of tolerance.",
        model_used="sonnet", topics=[],
    )
    hits = storage.search_messages("alice", "oscillator")
    assert len(hits) == 1
    assert hits[0]["conversation_id"] == "c1"
    assert "oscillator" in hits[0]["snippet"]
    assert hits[0]["role"] == "assistant"


def test_search_can_be_scoped_to_one_project():
    p = projects.create_project("alice", "Northgate")
    _conversation("inside", project_id=p["id"])
    _conversation("outside")
    for conv in ("inside", "outside"):
        storage.append_assistant_turn(
            conv, "alice", "holdover behaviour explained", model_used="sonnet", topics=[],
        )
    hits = storage.search_messages("alice", "holdover", project_id=p["id"])
    assert [h["conversation_id"] for h in hits] == ["inside"]


def test_search_never_crosses_users():
    _conversation("mine", "alice")
    _conversation("theirs", "bob")
    storage.append_assistant_turn("theirs", "bob", "secret holdover note", model_used="sonnet", topics=[])
    assert storage.search_messages("alice", "holdover") == []


def test_blank_search_returns_nothing_rather_than_everything():
    _conversation("c1")
    assert storage.search_messages("alice", "   ") == []


def test_search_excludes_deleted_conversations():
    _conversation("c1")
    storage.append_assistant_turn("c1", "alice", "holdover note", model_used="sonnet", topics=[])
    storage.delete_conversation("c1", "alice")
    assert storage.search_messages("alice", "holdover") == []


# ── Project instructions ────────────────────────────────────────────────────

def test_project_instructions_are_returned_for_the_owner_only():
    p = projects.create_project("alice", "Northgate", instructions="Lead with compliance.")
    assert projects.project_instructions(p["id"], "alice") == "Lead with compliance."
    assert projects.project_instructions(p["id"], "bob") == ""
    assert projects.project_instructions(None, "alice") == ""


def test_a_new_conversation_inherits_the_project_it_was_started_in():
    p = projects.create_project("alice", "Northgate")
    _conversation("c1", project_id=p["id"])
    assert storage.project_of("c1", "alice") == p["id"]
