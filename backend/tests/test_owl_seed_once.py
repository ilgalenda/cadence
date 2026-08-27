"""The account backfill runs once per user, not once per chat turn.

The original guard was "this user has no accounts yet". For a user whose history
names no company that condition never stops being true, so every `/api/owl/stream`
request re-read every research brief and the whole legacy campaign file — on the
request path, inside an async endpoint.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "seed-test-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import pytest  # noqa: E402

from agents.mind import memory_seed  # noqa: E402


@pytest.fixture
def store(monkeypatch):
    """An in-memory stand-in for the preference and account stores."""
    prefs: dict[str, dict[str, str]] = {}
    calls = {"seeded": 0}

    monkeypatch.setattr(memory_seed.memory, "get_preferences",
                        lambda u: dict(prefs.get(u, {})))
    monkeypatch.setattr(memory_seed.memory, "remember_preference",
                        lambda u, k, v: prefs.setdefault(u, {}).__setitem__(k, v))
    monkeypatch.setattr(memory_seed.memory, "list_accounts",
                        lambda u, status=None: [])

    def counted(username):
        calls["seeded"] += 1
        return 0
    monkeypatch.setattr(memory_seed, "seed_accounts_from_existing", counted)
    return calls, prefs


def test_a_user_with_nothing_to_seed_is_still_only_attempted_once(store):
    calls, _ = store
    for _ in range(5):
        memory_seed.seed_if_empty("sam")
    assert calls["seeded"] == 1


def test_the_attempt_is_recorded_even_when_it_seeds_nothing(store):
    _, prefs = store
    memory_seed.seed_if_empty("sam")
    assert memory_seed.SEEDED_KEY in prefs["sam"]


def test_the_marker_is_per_user(store):
    calls, _ = store
    memory_seed.seed_if_empty("sam")
    memory_seed.seed_if_empty("lasse")
    assert calls["seeded"] == 2


def test_a_broken_preference_store_never_costs_the_turn(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(memory_seed.memory, "get_preferences", boom)
    memory_seed.seed_if_empty("sam")   # must not raise
