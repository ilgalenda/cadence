"""X-ray must not let a degraded run pass for a clean one.

Three silent failures used to be possible, and each produced a result that was
indistinguishable from a good one:

  * a provider errored but some rows survived, and the error was dropped;
  * the model's turn was cut short, and the salvaged partial array was returned
    with ``error: None``;
  * ``Persona.md`` could not be found, so the search ran on the prompt's own
    generic ICP and nothing said so.

None of these change *whether* people come back — only how much you should trust
them — which is exactly why nothing caught them. These tests pin the fields that
now carry the truth.
"""
from __future__ import annotations

import pytest

from agents.mind import blocks
from agents.sales.xray import agent as xray_agent


class StubSource:
    """A discovery provider whose outcome the test dictates."""

    def __init__(self, name="web_search", results=None, error=None):
        self.name = name
        self._out = {"results": results or [], "raw": "raw", "error": error}

    @property
    def enabled(self):
        return True

    def discover(self, system_prompt, user_message):
        return dict(self._out)


def person(url="https://linkedin.com/in/a", **over):
    row = {
        "full_name": "Annika Lindqvist",
        "job_title": "Head of Market Infrastructure",
        "company": "Northgate",
        "linkedin_url": url,
        "confidence": "high",
        "recommended_path": "linkedin_direct",
        "match_reason": "Owns the clock-sync estate.",
    }
    row.update(over)
    return row


@pytest.fixture
def run(monkeypatch):
    """Run `shortlist` against whatever providers the test supplies."""
    monkeypatch.setattr(xray_agent, "_load_personas", lambda: ("PERSONAS", "data_root"))

    def go(sources):
        monkeypatch.setattr(xray_agent.name_sources, "enabled_sources", lambda: sources)
        return xray_agent.shortlist("sam", {"company": "Northgate"}, None, None)

    return go


def test_a_clean_run_reports_nothing_wrong(run):
    out = run([StubSource(results=[person()])])

    assert len(out["results"]) == 1
    assert out["error"] is None
    assert out["provider_errors"] == []
    assert out["truncated"] is False


def test_a_provider_error_survives_alongside_the_rows_it_did_return(run):
    # The old code read `error = None if merged else ...`, so one surviving row
    # erased the fact that a provider had failed. With a second source enabled
    # that is a half-empty shortlist presented as a whole one.
    out = run([
        StubSource(name="web_search", results=[person()]),
        StubSource(name="zoominfo", error="api_error: 502"),
    ])

    assert len(out["results"]) == 1
    # `error` keeps its narrow meaning, so routes and the eval floor are unmoved.
    assert out["error"] is None
    assert out["provider_errors"] == ["zoominfo: api_error: 502"]


def test_a_truncated_turn_is_flagged_even_though_rows_came_back(run):
    out = run([StubSource(results=[person()], error="incomplete_response: max_tokens")])

    assert len(out["results"]) == 1
    assert out["error"] is None
    assert out["truncated"] is True
    assert out["provider_errors"] == ["web_search: incomplete_response: max_tokens"]


def test_total_failure_still_sets_error(run):
    out = run([StubSource(error="api_error: overloaded")])

    assert out["results"] == []
    assert out["error"] == "web_search: api_error: overloaded"
    assert out["provider_errors"] == ["web_search: api_error: overloaded"]


def test_an_ordinary_error_is_not_mistaken_for_truncation(run):
    out = run([StubSource(results=[person()], error="api_error: 500")])

    assert out["truncated"] is False


def test_every_early_return_answers_the_whole_contract(monkeypatch):
    # A caller reading `truncated` should never meet a KeyError just because the
    # search stopped before it started.
    monkeypatch.setattr(xray_agent, "_load_personas", lambda: ("", "missing"))
    monkeypatch.setattr(xray_agent.name_sources, "enabled_sources", lambda: [])

    no_company = xray_agent.shortlist("sam", {}, None, None)
    no_sources = xray_agent.shortlist("sam", {"company": "Northgate"}, None, None)

    for out in (no_company, no_sources):
        assert set(out) >= {"results", "grouped", "raw", "error", "provider_errors",
                            "truncated", "persona_source"}
    assert no_company["error"] == "missing_company"
    assert no_sources["error"] == "no_enabled_sources"
    assert no_sources["persona_source"] == "missing"


def test_the_shortlist_says_which_persona_file_shaped_it(run):
    out = run([StubSource(results=[person()])])

    assert out["persona_source"] == "data_root"


# ── The persona file itself ─────────────────────────────────────────────────

def test_persona_provenance_falls_back_in_order(monkeypatch, tmp_path):
    data_root = tmp_path / "data" / "company" / "knowledge"
    repo = tmp_path / "repo" / "vault" / "company" / "knowledge"
    data_root.mkdir(parents=True)
    repo.mkdir(parents=True)
    repo.joinpath("Persona.md").write_text("repo copy", encoding="utf-8")

    monkeypatch.setattr(blocks, "vault_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(blocks, "REPO_ROOT", tmp_path / "repo")

    assert blocks.load_customer_personas_with_source() == ("repo copy", "repo")

    data_root.joinpath("Persona.md").write_text("live copy", encoding="utf-8")
    assert blocks.load_customer_personas_with_source() == ("live copy", "data_root")


def test_persona_provenance_is_missing_when_there_is_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(blocks, "vault_dir", lambda: tmp_path / "nowhere")
    monkeypatch.setattr(blocks, "REPO_ROOT", tmp_path / "also-nowhere")

    assert blocks.load_customer_personas_with_source() == ("", "missing")


def test_the_real_persona_file_strips_cleanly():
    # The stripper is a regex over a file that came out of TextEdit, and it is
    # one paste away from quietly returning mush. If this goes red, X-ray is
    # being targeted by something that is no longer a list of job titles.
    text, source = blocks.load_customer_personas_with_source()

    if source == "missing":
        pytest.skip("no customer personas in this vault — the public build ships none")
    assert source in {"data_root", "repo"}, "Persona.md is missing from both vaults"
    assert "Network Architect" in text
    assert "\\" not in text, "RTF control characters survived the strip"
