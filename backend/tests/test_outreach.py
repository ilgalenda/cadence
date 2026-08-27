"""Tests for the Outreach primitives service (two-pass, style-aware compose)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.services import outreach


@pytest.fixture
def no_style(monkeypatch):
    monkeypatch.setattr(outreach.style_personalisation, "style_block", lambda u, **k: "")


def _recorded_requests_text(recording_anthropic) -> str:
    return json.dumps([kw for m, kw in recording_anthropic.calls if m == "create"], default=str)


def test_compose_json_parses_mind_result(recording_anthropic, no_style):
    recording_anthropic.create_text = '{"touches": [{"channel": "email"}]}'
    out = outreach.compose_json(username="sam", role_overlay="ROLE", user_prompt="draft this")
    assert out == {"touches": [{"channel": "email"}]}
    assert any(m == "create" for m, _ in recording_anthropic.calls)


def test_style_overlay_injected_when_personalised(recording_anthropic, monkeypatch):
    monkeypatch.setattr(outreach.style_personalisation, "style_block", lambda u, **k: "USERVOICE-MARKER")
    recording_anthropic.create_text = "{}"
    outreach.compose_json(username="sam", role_overlay="ROLE", user_prompt="p", personalise=True)
    assert "USERVOICE-MARKER" in _recorded_requests_text(recording_anthropic)


def test_style_overlay_absent_when_not_personalised(recording_anthropic, monkeypatch):
    monkeypatch.setattr(outreach.style_personalisation, "style_block", lambda u, **k: "USERVOICE-MARKER")
    recording_anthropic.create_text = "{}"
    outreach.compose_json(username="sam", role_overlay="ROLE", user_prompt="p", personalise=False)
    assert "USERVOICE-MARKER" not in _recorded_requests_text(recording_anthropic)


def test_two_pass_drafts_then_refines(recording_anthropic, no_style):
    recording_anthropic.create_text = '{"v": 1}'
    seen = {}

    def refine_prompt(draft):
        seen["draft"] = draft
        return "refine now"

    out = outreach.two_pass(
        username="sam", draft_overlay="D", draft_prompt="draft",
        refine_overlay="R", refine_prompt=refine_prompt,
    )
    assert out == {"v": 1}
    assert seen["draft"] == {"v": 1}                                    # refine got the parsed draft
    assert sum(1 for m, _ in recording_anthropic.calls if m == "create") == 2   # two passes


def test_two_pass_refine_failure_returns_draft(recording_anthropic, no_style):
    recording_anthropic.create_text = '{"v": 7}'

    def bad_refine(draft):
        raise RuntimeError("boom")

    out = outreach.two_pass(
        username="sam", draft_overlay="D", draft_prompt="draft",
        refine_overlay="R", refine_prompt=bad_refine,
    )
    assert out == {"v": 7}                                              # draft returned unchanged
