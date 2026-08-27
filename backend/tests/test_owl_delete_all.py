"""Deleting every conversation at once.

Mirrors the single-conversation contract: rows are soft-deleted so correction
provenance pointing at them survives, message bodies are hard-deleted, and the
operation is idempotent.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "delete-all-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import pytest  # noqa: E402

from agents.owl import db, storage  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "owl.db")
    db.init_db()


def _conversation(username: str, conv_id: str, *, archived: bool = False) -> None:
    storage.append_user_turn(
        conv_id, username, "a question",
        title="A conversation", model_used="haiku", topics=[], project_id=None,
    )
    if archived:
        storage.set_archived(conv_id, username, True)


def test_deletes_every_conversation_and_reports_the_count():
    for i in range(3):
        _conversation("sam", f"c{i}")
    assert storage.delete_all_conversations("sam") == 3
    assert storage.list_conversations("sam") == []


def test_includes_archived_conversations():
    _conversation("sam", "loose")
    _conversation("sam", "filed-away", archived=True)
    assert storage.delete_all_conversations("sam") == 2
    assert storage.list_conversations("sam", include_archived=True) == []


def test_never_reaches_another_user():
    _conversation("sam", "mine")
    _conversation("lasse", "theirs")
    assert storage.delete_all_conversations("sam") == 1
    assert len(storage.list_conversations("lasse")) == 1


def test_is_idempotent():
    _conversation("sam", "one")
    assert storage.delete_all_conversations("sam") == 1
    assert storage.delete_all_conversations("sam") == 0


def test_on_an_empty_account_it_is_a_no_op():
    assert storage.delete_all_conversations("nobody") == 0


def test_message_bodies_are_destroyed_but_the_row_survives_for_provenance():
    _conversation("sam", "c1")
    storage.delete_all_conversations("sam")
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = 'c1'"
        ).fetchone()["n"] == 0
        row = conn.execute("SELECT deleted_at FROM conversations WHERE id = 'c1'").fetchone()
        assert row is not None and row["deleted_at"] is not None
