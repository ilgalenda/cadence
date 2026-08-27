"""Naming a conversation from its opening exchange.

The title used to be `last_user_msg[:80]` — the question, cut mid-word, locked
at creation and never revisited. These cover the generator that replaced it, and
in particular that it is *optional*: a conversation must survive its own naming
failing, because the row already exists by the time this runs.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "title-test-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import pytest  # noqa: E402

from agents.owl import routes  # noqa: E402


class _Result:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def says(monkeypatch):
    """Make the classifier return `text`, and record what it was asked."""
    seen = {}

    def _install(text: str):
        def fake_classify(*, system, messages, max_tokens=None):
            seen["system"] = system
            seen["content"] = messages[0]["content"]
            seen["max_tokens"] = max_tokens
            return _Result(text)
        monkeypatch.setattr(routes.mind, "classify", fake_classify)
        return seen

    return _install


def test_names_the_conversation_from_the_exchange(says):
    seen = says("Case study for a tier-one bank")
    assert routes._generate_title("Which case study for a bank?", "Use the Northgate one.") \
        == "Case study for a tier-one bank"
    # Both halves inform the name — an answer often identifies the subject the
    # question only gestured at.
    assert "Which case study for a bank?" in seen["content"]
    assert "Use the Northgate one." in seen["content"]


def test_strips_the_quoting_and_punctuation_models_add(says):
    says('"PTP² Mesh versus boundary clocks."')
    assert routes._generate_title("q", "a") == "PTP² Mesh versus boundary clocks"


def test_keeps_only_the_first_line_when_the_model_adds_prose(says):
    says("Galileo OSNMA explained\n\nI hope this helps!")
    assert routes._generate_title("q", "a") == "Galileo OSNMA explained"


def test_treats_an_over_long_answer_as_a_refusal(says):
    # Truncating this would produce a worse title than the one already on the
    # row, so it declines instead.
    says(" ".join(["word"] * (routes.TITLE_MAX_WORDS + 1)))
    assert routes._generate_title("q", "a") == ""


def test_declines_when_the_model_returns_nothing(says):
    says("   ")
    assert routes._generate_title("q", "a") == ""


def test_survives_the_model_failing(monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(routes.mind, "classify", boom)
    assert routes._generate_title("q", "a") == ""


def test_declines_on_an_empty_question_without_calling_the_model(monkeypatch):
    def never(**_kwargs):
        raise AssertionError("the model should not be asked to name nothing")
    monkeypatch.setattr(routes.mind, "classify", never)
    assert routes._generate_title("   ", "an answer") == ""
