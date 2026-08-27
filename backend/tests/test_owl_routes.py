"""Route-level tests for Owl's organisation surface — the endpoints the workspace calls.

`test_owl_organisation.py` covers the storage layer directly. This file covers the
HTTP contract on top of it: status codes, request bodies, query filters, and the
error mapping the UI relies on to tell "you asked for something illegal" (400)
apart from "it isn't there" (404).

Two gates stand in front of these routes, and both are exercised deliberately:
an HTTP middleware that rejects any `/api/` request without a session, and the
`require_authed` dependency that resolves a session to a real user.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

import itsdangerous
import pytest

# main.py reads these at import time, so they are set before it is imported.
# DATA_ROOT points at a throwaway directory so no test can reach real state.
# Defaults, never overwrites: another route-test module may have imported main
# already, and the cookie below has to be signed with whatever secret the app
# actually loaded. Assigning our own unconditionally made this module pass only
# while it happened to be imported first.
os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "route-test-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

_SECRET = os.environ["SESSION_SECRET"]

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agents.owl import db, storage  # noqa: E402
from auth import require_authed  # noqa: E402

USER = "router-test-user"


def _session_cookie(user: str = USER) -> str:
    """The same signed cookie Starlette's SessionMiddleware would set."""
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(_SECRET).sign(payload).decode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """An authenticated client over a throwaway database."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "owl.db")
    db.init_db()
    main.app.dependency_overrides[require_authed] = lambda: {"username": USER, "access": "admin"}
    with TestClient(main.app, cookies={"cadence_session": _session_cookie()}) as c:
        yield c
    main.app.dependency_overrides.clear()


def _seed_conversation(conv_id: str, *, reply: str | None = None) -> None:
    """Create a conversation the way the chat route does — user turn first."""
    storage.append_user_turn(
        conv_id, USER, f"question {conv_id}",
        title=f"Conv {conv_id}", model_used="sonnet", topics=[],
    )
    if reply:
        storage.append_assistant_turn(conv_id, USER, reply, model_used="sonnet", topics=[])


def _project(client, name="Northgate", instructions="") -> dict:
    res = client.post("/api/owl/projects", json={"name": name, "instructions": instructions})
    assert res.status_code == 201, res.text
    return res.json()


# ── Authentication ──────────────────────────────────────────────────────────

def test_api_requires_a_session(tmp_path, monkeypatch):
    """The middleware refuses before any dependency runs, so an overridden
    `require_authed` must not be enough to get in without a session."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "owl.db")
    db.init_db()
    main.app.dependency_overrides[require_authed] = lambda: {"username": USER}
    try:
        with TestClient(main.app) as anonymous:
            assert anonymous.get("/api/owl/projects").status_code == 401
    finally:
        main.app.dependency_overrides.clear()


# ── Projects ────────────────────────────────────────────────────────────────

def test_projects_start_empty(client):
    assert client.get("/api/owl/projects").json() == []


def test_create_project_returns_201_and_the_row(client):
    project = _project(client, "Northgate", "Lead with compliance.")
    assert project["name"] == "Northgate"
    assert project["instructions"] == "Lead with compliance."
    assert project["archived"] is False


def test_create_project_rejects_a_blank_name(client):
    assert client.post("/api/owl/projects", json={"name": "   "}).status_code == 400


def test_patch_project_updates_only_what_was_sent(client):
    project = _project(client, "Northgate", "Original.")
    res = client.patch(f"/api/owl/projects/{project['id']}", json={"name": "Northgate Nordics"})
    assert res.status_code == 200
    assert res.json()["name"] == "Northgate Nordics"
    assert res.json()["instructions"] == "Original.", "an omitted field must be left alone"


def test_patch_project_with_nothing_to_change_is_a_bad_request(client):
    project = _project(client)
    assert client.patch(f"/api/owl/projects/{project['id']}", json={}).status_code == 400


def test_unknown_project_is_404_not_400(client):
    assert client.get("/api/owl/projects/nope").status_code == 404
    assert client.patch("/api/owl/projects/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/owl/projects/nope").status_code == 404


def test_archive_hides_a_project_until_asked_for(client):
    project = _project(client)
    assert client.post(f"/api/owl/projects/{project['id']}/archive", json={"archived": True}).status_code == 200
    assert client.get("/api/owl/projects").json() == []
    assert len(client.get("/api/owl/projects?include_archived=true").json()) == 1


def test_reorder_applies_the_order_and_puts_unlisted_projects_behind(client):
    a, b, c = _project(client, "A"), _project(client, "B"), _project(client, "C")
    res = client.post("/api/owl/projects/reorder", json={"ordered_ids": [c["id"], a["id"]]})
    assert res.status_code == 200
    assert [p["name"] for p in client.get("/api/owl/projects").json()] == ["C", "A", "B"]
    assert b["id"] == client.get("/api/owl/projects").json()[2]["id"]


def test_reorder_rejects_an_unknown_id(client):
    assert client.post("/api/owl/projects/reorder", json={"ordered_ids": ["bogus"]}).status_code == 400


# ── Folders ─────────────────────────────────────────────────────────────────

def test_folders_are_returned_nested(client):
    project = _project(client)
    parent = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "Discovery"}).json()
    child = client.post(
        f"/api/owl/projects/{project['id']}/folders",
        json={"name": "Calls", "parent_id": parent["id"]},
    ).json()

    tree = client.get(f"/api/owl/projects/{project['id']}/folders").json()
    assert [f["id"] for f in tree] == [parent["id"]]
    assert [f["id"] for f in tree[0]["children"]] == [child["id"]]


def test_folder_move_into_its_own_descendant_is_refused(client):
    project = _project(client)
    parent = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "A"}).json()
    child = client.post(
        f"/api/owl/projects/{project['id']}/folders",
        json={"name": "B", "parent_id": parent["id"]},
    ).json()

    res = client.patch(f"/api/owl/folders/{parent['id']}", json={"parent_id": child["id"], "move": True})
    assert res.status_code == 400
    assert "descendant" in res.json()["detail"]


def test_folder_patch_distinguishes_rename_from_move(client):
    """`parent_id: null` without `move` renames only — it must not silently
    relocate the folder to the project root."""
    project = _project(client)
    parent = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "A"}).json()
    child = client.post(
        f"/api/owl/projects/{project['id']}/folders",
        json={"name": "B", "parent_id": parent["id"]},
    ).json()

    res = client.patch(f"/api/owl/folders/{child['id']}", json={"name": "B renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "B renamed"
    assert res.json()["parent_id"] == parent["id"], "a rename must not move the folder"


def test_folder_patch_with_nothing_to_do_is_a_bad_request(client):
    project = _project(client)
    folder = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "A"}).json()
    assert client.patch(f"/api/owl/folders/{folder['id']}", json={}).status_code == 400


# ── Placement ───────────────────────────────────────────────────────────────

def test_placement_files_a_conversation_into_a_folder(client):
    project = _project(client)
    folder = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "Discovery"}).json()
    _seed_conversation("c1")

    res = client.patch(
        "/api/owl/sessions/c1/placement",
        json={"project_id": project["id"], "folder_id": folder["id"]},
    )
    assert res.status_code == 200
    session = client.get("/api/owl/sessions/c1").json()
    assert session["project_id"] == project["id"]
    assert session["folder_id"] == folder["id"]


def test_placement_rejects_a_folder_without_its_project(client):
    project = _project(client)
    folder = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "Discovery"}).json()
    _seed_conversation("c1")

    res = client.patch("/api/owl/sessions/c1/placement", json={"folder_id": folder["id"]})
    assert res.status_code == 400
    assert "requires its project" in res.json()["detail"]


def test_placement_of_an_unknown_conversation_is_404(client):
    assert client.patch("/api/owl/sessions/nope/placement", json={}).status_code == 404


def test_session_filters_scope_to_a_branch_of_the_tree(client):
    project = _project(client)
    _seed_conversation("filed")
    _seed_conversation("loose")
    client.patch("/api/owl/sessions/filed/placement", json={"project_id": project["id"]})

    in_project = client.get(f"/api/owl/sessions?project_id={project['id']}").json()
    unfiled = client.get("/api/owl/sessions?unfiled=true").json()
    assert [c["id"] for c in in_project] == ["filed"]
    assert [c["id"] for c in unfiled] == ["loose"]


# ── Pinning & archiving ─────────────────────────────────────────────────────

def test_pinned_conversations_sort_above_newer_ones(client):
    _seed_conversation("old")
    _seed_conversation("new")
    assert client.post("/api/owl/sessions/old/pin", json={"pinned": True}).status_code == 200
    assert client.get("/api/owl/sessions").json()[0]["id"] == "old"


def test_archiving_hides_a_conversation_but_keeps_its_messages(client):
    _seed_conversation("c1", reply="an answer")
    assert client.post("/api/owl/sessions/c1/archive", json={"archived": True}).status_code == 200
    assert client.get("/api/owl/sessions").json() == []
    assert len(client.get("/api/owl/sessions?include_archived=true").json()) == 1
    assert len(client.get("/api/owl/sessions/c1").json()["messages"]) == 2


def test_pin_and_archive_on_an_unknown_conversation_are_404(client):
    assert client.post("/api/owl/sessions/nope/pin", json={"pinned": True}).status_code == 404
    assert client.post("/api/owl/sessions/nope/archive", json={"archived": True}).status_code == 404


# ── Search ──────────────────────────────────────────────────────────────────

def test_search_returns_a_hit_per_message_with_a_snippet(client):
    _seed_conversation("c1", reply="A grandmaster in holdover runs on its own oscillator.")
    hits = client.get("/api/owl/search?q=oscillator").json()
    assert len(hits) == 1
    assert hits[0]["conversation_id"] == "c1"
    assert hits[0]["role"] == "assistant"
    assert "oscillator" in hits[0]["snippet"]


def test_search_can_be_scoped_to_one_project(client):
    project = _project(client)
    _seed_conversation("inside", reply="holdover behaviour")
    _seed_conversation("outside", reply="holdover behaviour")
    client.patch("/api/owl/sessions/inside/placement", json={"project_id": project["id"]})

    hits = client.get(f"/api/owl/search?q=holdover&project_id={project['id']}").json()
    assert [h["conversation_id"] for h in hits] == ["inside"]


def test_blank_search_returns_nothing_rather_than_everything(client):
    _seed_conversation("c1", reply="something")
    assert client.get("/api/owl/search?q=%20%20").json() == []


# ── Deleting a container never destroys conversations ───────────────────────

def test_deleting_a_folder_lifts_its_conversations_to_the_project_root(client):
    project = _project(client)
    folder = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "Discovery"}).json()
    _seed_conversation("c1", reply="an answer")
    client.patch(
        "/api/owl/sessions/c1/placement",
        json={"project_id": project["id"], "folder_id": folder["id"]},
    )

    res = client.delete(f"/api/owl/folders/{folder['id']}")
    assert res.status_code == 200
    assert res.json()["conversations_released"] == 1

    session = client.get("/api/owl/sessions/c1").json()
    assert session["project_id"] == project["id"]
    assert session["folder_id"] is None
    assert len(session["messages"]) == 2


def test_deleting_a_project_unfiles_its_conversations_rather_than_deleting_them(client):
    project = _project(client)
    folder = client.post(f"/api/owl/projects/{project['id']}/folders", json={"name": "Discovery"}).json()
    _seed_conversation("c1", reply="an answer")
    client.patch(
        "/api/owl/sessions/c1/placement",
        json={"project_id": project["id"], "folder_id": folder["id"]},
    )

    res = client.delete(f"/api/owl/projects/{project['id']}")
    assert res.status_code == 200
    assert res.json()["conversations_unfiled"] == 1

    session = client.get("/api/owl/sessions/c1").json()
    assert session["project_id"] is None
    assert session["folder_id"] is None
    assert len(session["messages"]) == 2, "the transcript must survive its project"
    assert client.get("/api/owl/projects").json() == []
