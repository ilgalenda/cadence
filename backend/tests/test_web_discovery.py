"""The acceptance bar for web-search people discovery.

Written as a characterisation net over the two discovery pipelines — the lead X-ray
name-source and high-intent detection — before they were unified behind
`agents.services.web_discovery`. The unification is done and `agents/lead` is gone,
so the merge/dedup/rank/group cases were **repointed at `sales/xray/agent.shortlist`**
in Stage 3.3 rather than deleted with the old pipeline: that transformation is still
the product's behaviour, it is still the thing most likely to break silently, and
nothing else covers it.

Assertions are on the deterministic transformation (normalise → dedup → rank →
group), driven through the mocked SDK boundary (`recording_anthropic`); model output
itself is canned.
"""
import json

from agents.services import name_sources, web_discovery
from agents.sales import prompts as sales_prompts
from agents.sales import signal_prompts
from agents.sales.signals import agent as signals_agent
from agents.sales.xray import agent as xray_agent


# --- lead X-ray: WebSearchNameSource.discover ------------------------------

def test_websearch_discover_normalises_and_tags_source(recording_anthropic):
    recording_anthropic.create_text = json.dumps([
        {
            "full_name": "Jane Doe", "job_title": "Head of Trading Infra",
            "company": "Acme", "linkedin_url": "https://linkedin.com/in/jane",
            "confidence": "HIGH", "recommended_path": "linkedin_direct",
            "match_reason": "Runs low-latency infra", "source_query": "acme trading",
        },
        {"job_title": "no name -> dropped"},  # missing full_name/match_reason
    ])
    out = name_sources.WebSearchNameSource().discover("SYS", "MSG")
    assert out["error"] is None
    assert len(out["results"]) == 1
    row = out["results"][0]
    assert row["full_name"] == "Jane Doe"
    assert row["confidence"] == "high"          # normalised to lowercase
    assert row["recommended_path"] == "linkedin_direct"
    assert row["source"] == "web_search"        # tagged with provider name


def test_websearch_discover_bad_path_defaults_to_campaign_context(recording_anthropic):
    recording_anthropic.create_text = json.dumps([
        {"full_name": "X", "match_reason": "y", "recommended_path": "nonsense"},
    ])
    out = name_sources.WebSearchNameSource().discover("SYS", "MSG")
    assert out["results"][0]["recommended_path"] == "campaign_context"


def test_websearch_discover_parse_failure_surfaces_error(recording_anthropic):
    recording_anthropic.create_text = "not json at all"
    out = name_sources.WebSearchNameSource().discover("SYS", "MSG")
    assert out["results"] == []
    assert out["error"].startswith("parse_failed")


def test_websearch_discover_incomplete_still_returns_rows(recording_anthropic):
    # A non-end_turn stop still salvages parsed rows, but flags incompleteness.
    recording_anthropic.stop_reason = "max_tokens"
    recording_anthropic.create_text = json.dumps([
        {"full_name": "Jane", "match_reason": "fit", "recommended_path": "linkedin_direct"},
    ])
    out = name_sources.WebSearchNameSource().discover("SYS", "MSG")
    assert len(out["results"]) == 1
    assert out["error"] == "incomplete_response: max_tokens"


# --- X-ray: shortlist merge / dedup / rank / group -------------------------

class _FakeSource:
    def __init__(self, name, rows):
        self.name = name
        self._rows = rows

    def discover(self, system_prompt, user_message):
        return {"results": self._rows, "raw": f"raw-{self.name}", "error": None}


def _row(name, url, path, conf, source):
    return {
        "full_name": name, "job_title": "", "company": "Acme",
        "linkedin_url": url, "confidence": conf, "recommended_path": path,
        "match_reason": "fit", "source_query": "", "source": source,
    }


def test_the_shortlist_merges_dedups_ranks_and_groups(monkeypatch):
    monkeypatch.setattr(sales_prompts, "xray_user_payload",
                        lambda *a, **k: {"company_name": "Acme"})
    monkeypatch.setattr(sales_prompts, "xray_system_prompt", lambda *a, **k: "SYS")
    monkeypatch.setattr(sales_prompts, "xray_user_message", lambda *a, **k: "MSG")
    # The loader now reports where the personas came from as well, because a
    # silent fallback to the generic ICP changes who a search finds.
    monkeypatch.setattr(xray_agent, "_load_personas", lambda: ("PERSONAS", "data_root"))

    primary = _FakeSource("web_search", [
        _row("Jane", "https://li/in/jane", "linkedin_direct", "high", "web_search"),
        _row("Context Only", "https://li/in/ctx", "campaign_context", "low", "web_search"),
    ])
    secondary = _FakeSource("zoominfo", [
        # Duplicate of Jane by URL — earlier source must win the dedupe.
        _row("Jane Dup", "https://li/in/jane", "email_enrichment", "medium", "zoominfo"),
        _row("Bob", "https://li/in/bob", "email_enrichment", "high", "zoominfo"),
    ])
    monkeypatch.setattr(name_sources, "enabled_sources",
                        lambda: [primary, secondary])

    out = xray_agent.shortlist("sam", {"final": True}, {"structured": True})

    assert out["error"] is None
    names = [r["full_name"] for r in out["results"]]
    assert names == ["Jane", "Bob", "Context Only"]      # ranked; Jane (dup) deduped, earlier source kept
    assert out["results"][0]["intent_score"] > out["results"][-1]["intent_score"]
    assert [r["full_name"] for r in out["grouped"]["linkedin_direct"]] == ["Jane"]
    assert [r["full_name"] for r in out["grouped"]["email_enrichment"]] == ["Bob"]
    assert [r["full_name"] for r in out["grouped"]["campaign_context"]] == ["Context Only"]


def test_a_shortlist_with_no_company_short_circuits_before_spending_a_search(monkeypatch):
    monkeypatch.setattr(sales_prompts, "xray_user_payload", lambda *a, **k: {})
    out = xray_agent.shortlist("sam", None, None)
    assert out["error"] == "missing_company"
    assert out["results"] == []


# --- signal detection: normalise / dedup / cap -----------------------------
# This behaviour came from `high_intent`'s detection pipeline, which R4 deleted,
# and lived in X-ray's signal mode until 2026-08-24. It has moved again, to
# Signals — where a signal is already the subject — and the cap and URL dedup
# came with it unchanged. The test follows the behaviour, as it did last time.

def test_detection_normalises_dedups_by_url_and_caps(monkeypatch, recording_anthropic):
    monkeypatch.setattr(signal_prompts, "detection_user_message", lambda *a, **k: "MSG")
    rows = [
        {"full_name": f"P{i}", "signal_context": "visited pricing", "confidence": "high",
         "linkedin_url": f"https://li/in/p{i}"}
        for i in range(20)
    ]
    # Two duplicate URLs that must collapse to one.
    rows.append({"full_name": "Dup", "signal_context": "again", "linkedin_url": "https://li/in/p0"})
    recording_anthropic.create_text = json.dumps(rows)

    out = signals_agent.detect("sam", "pricing_visit", {"icp": True})
    assert out["error"] is None
    assert len(out["results"]) == signals_agent.DETECTION_MAX_RESULTS   # capped at 15
    urls = [r["linkedin_url"] for r in out["results"]]
    assert len(urls) == len(set(urls))                               # deduped
    assert all(r["confidence"] in {"high", "medium", "low"} for r in out["results"])


# --- citation markup must not reach the shortlist --------------------------
# The pinned (pre-dynamic-filtering) web_search generation wraps quoted spans in
# `<cite index="4-1">…</cite>` inside the very strings the page displays. The
# markup is presentation, not sentence, so it is stripped on the way in.

def test_normalise_row_strips_citation_markup():
    from agents.services.name_sources import normalise_row

    row = normalise_row(
        {
            "full_name": '<cite index="1-2">Tal Cohen</cite>',
            "job_title": 'VP of <cite index="4-1">Northgate Nordics</cite>',
            "company": "Northgate Nordics",
            "linkedin_url": "https://li/in/tal",
            "confidence": "high",
            "recommended_path": "linkedin_direct",
            "match_reason": 'Cohen <cite index="4-1">runs the exchange</cite> and owns timing spend.',
            "source_query": "q",
        },
        "web_search",
    )

    assert row["full_name"] == "Tal Cohen"
    assert row["job_title"] == "VP of Northgate Nordics"
    assert row["match_reason"] == "Cohen runs the exchange and owns timing spend."
    assert "<cite" not in "".join(str(v) for v in row.values())


def test_normalise_row_drops_row_that_was_only_citation_markup():
    """A name that is nothing but markup is not a name."""
    from agents.services.name_sources import normalise_row

    assert normalise_row(
        {"full_name": "<cite index=\"1-1\"></cite>", "match_reason": "reason"},
        "web_search",
    ) is None


# --- a truncated research turn is reported, not silently halved -------------
# `run_tool_loop`'s max_tokens continuation is right for chat and wrong here:
# research answers with one terminal JSON document, so continuing splits the
# array across two messages and hands the caller an unparseable fragment.

def test_research_turn_does_not_continue_past_max_tokens(recording_anthropic):
    recording_anthropic.create_text = '[{"full_name": "A", "signal_context": "x"}'
    recording_anthropic.stop_reason = "max_tokens"

    out = web_discovery.search_people(
        system="S",
        user_message="U",
        normalise=lambda row: row,
        tool_choice={"type": "auto"},
        max_uses=3,
    )

    # `only` asserts exactly one create call — no continuation nudge was sent.
    recording_anthropic.only("create")
    assert out["error"] and "max_tokens" in out["error"]


# --- a scored lead grounds discovery without a buying signal ----------------
# When the search starts from a scored lead, the lead *is* the signal: its
# behaviour is why we are searching at all. Restating it to the discovery prompt
# adds nothing and costs accuracy, and one form of it was an outright category
# error — a scoring verdict carries no industry, so `signal_type` fell through to
# the industry slot and every lead-grounded search claimed the company's vertical
# was "Inbound action". (Sam, 2026-08-05.)

#: The shape `/leads/analyze` actually returns — note there is no industry key.
SCORED_LEAD = {
    "contact_name": "Ada Lovelace",
    "company": "Northgate Nordics",
    "role": "Head of Infrastructure",
    "signal_strength": "Hot",
    "signal_type": "Inbound action",
    "product_fit": "PTP grandmaster + GNSS",
    "confidence": "high",
}


def test_a_buying_signal_is_never_described_as_the_industry():
    payload = sales_prompts.xray_user_payload(SCORED_LEAD, None)
    assert "industry" not in payload

    message = sales_prompts.xray_user_message(payload)
    assert "Inbound action" not in message
    assert "Industry / vertical" not in message


def test_no_buying_signal_reaches_the_discovery_prompt():
    """Neither the signal's type nor its strength is an input to who to find."""
    payload = sales_prompts.xray_user_payload(SCORED_LEAD, None)
    assert "signal_strength" not in payload
    assert "signal_type" not in payload

    message = sales_prompts.xray_user_message(payload)
    for leaked in ("Signal strength", "Hot", "Inbound action", "No signal"):
        assert leaked not in message, f"{leaked!r} leaked into the discovery prompt"


def test_the_lead_still_grounds_who_to_look_for():
    """Stripping the signal must not strip the useful grounding with it.

    The product line implies the technical function that would own it, and the
    role already seen is a title hint for finding that person's peers — that is
    the whole reason a lead-grounded search beats typing the company name.
    """
    message = sales_prompts.xray_user_message(
        sales_prompts.xray_user_payload(SCORED_LEAD, None)
    )
    assert "Northgate Nordics" in message
    assert "PTP grandmaster + GNSS" in message
    assert "Head of Infrastructure" in message


def test_a_real_industry_is_still_used_when_one_is_known():
    """The chain was narrowed, not removed — a genuine vertical still lands."""
    payload = sales_prompts.xray_user_payload(
        SCORED_LEAD, {"industry": "Capital markets", "domain": "northgate.com"}
    )
    assert payload["industry"] == "Capital markets"
    assert payload["domain"] == "northgate.com"
    assert "Industry / vertical: Capital markets" in sales_prompts.xray_user_message(payload)


def test_a_no_signal_verdict_cannot_poison_the_vertical():
    """The worst observed case: "No signal" presented as the company's vertical."""
    payload = sales_prompts.xray_user_payload(
        {"company": "Acme", "signal_type": "No signal"}, None
    )
    assert "industry" not in payload
    assert "No signal" not in sales_prompts.xray_user_message(payload)
