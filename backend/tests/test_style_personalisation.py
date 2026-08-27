"""Tests for the Style Personalisation service."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.services import style_personalisation as style


@pytest.fixture
def style_db(tmp_path, monkeypatch):
    """Point the store at a throwaway db per test."""
    monkeypatch.setattr(style, "DB_PATH", tmp_path / "style.db")
    style.init_db()
    return style


def test_add_and_list_samples_are_per_user(style_db):
    style_db.add_sample("sam", "Hi there, quick one —")
    style_db.add_sample("sam", "Following up on my last note.")
    assert len(style_db.list_samples("sam")) == 2
    assert style_db.list_samples("roy") == []          # isolated by user


def test_add_sample_requires_text(style_db):
    with pytest.raises(ValueError):
        style_db.add_sample("sam", "   ")


def test_distil_profile_uses_mind_and_persists(style_db, recording_anthropic):
    recording_anthropic.create_text = "- Warm, direct; short sentences.\n- Sign-off: 'Cheers, Sam'."
    style_db.add_sample("sam", "Hey — quick one. Cheers, Sam")
    profile = style_db.distil_profile("sam")
    assert "Cheers, Sam" in profile
    assert style_db.get_profile("sam") == profile     # persisted


def test_distil_with_no_samples_returns_none(style_db):
    assert style_db.distil_profile("nobody") is None
    assert style_db.get_profile("nobody") is None


def test_style_block_is_empty_without_a_profile(style_db):
    # No-op until learned, so composition falls back to Owl's own voice.
    style_db.add_sample("sam", "a sample but never distilled")
    assert style_db.style_block("sam") == ""


def test_style_block_carries_profile_and_exemplars(style_db, recording_anthropic):
    recording_anthropic.create_text = "STYLE: warm, brief, British."
    style_db.add_sample("sam", "Sample one text.")
    style_db.add_sample("sam", "Sample two text.")
    style_db.distil_profile("sam")

    block = style_db.style_block("sam")
    assert "USER WRITING STYLE" in block               # the instruction framing
    assert "sent by the user as themselves" in block
    assert "STYLE: warm, brief, British." in block     # the distilled profile
    assert "Sample one text." in block or "Sample two text." in block  # exemplars


def test_one_users_style_never_leaks_to_another(style_db, recording_anthropic):
    recording_anthropic.create_text = "sam's distinctive profile"
    style_db.add_sample("sam", "sam writing")
    style_db.distil_profile("sam")
    # roy has learned nothing → empty overlay, no trace of sam's profile.
    roy_block = style_db.style_block("roy")
    assert roy_block == ""
    assert "sam" not in roy_block
