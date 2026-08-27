"""The order a shortlist arrives in.

X-ray returns up to fifteen people on purpose and nobody reads row twelve, so
the order is where most of the agent's usefulness lives. The ranking this tests
replaced could produce only nine distinct scores across fifteen rows, which left
the head of the list resolved by provider emission order — arbitrary.

Two things these must hold on to:

  * the coarse tier still dominates, so evidence can reorder *within* a tier but
    never lift a context-only mention above a confirmed profile;
  * the persona weighting follows Acme's own call corpus, not taste.
"""
from __future__ import annotations

from agents.sales.xray import ranking


def row(**over):
    base = {
        "full_name": "Annika Lindqvist",
        "job_title": "Network Architect",
        "linkedin_url": "https://www.linkedin.com/in/annika",
        "confidence": "high",
        "recommended_path": "linkedin_direct",
        "match_reason": "Owns the clock-sync estate.",
        "company_domain": "northgate.com",
    }
    base.update(over)
    return base


# ── The predicates ──────────────────────────────────────────────────────────

def test_a_truncated_display_name_is_not_usable():
    assert ranking.is_usable_name("Annika Lindqvist")
    assert not ranking.is_usable_name("Alan T.")
    assert not ranking.is_usable_name("Madonna")
    # The parenthesised nickname hides the initial that makes it truncated.
    assert not ranking.is_usable_name("Xule Z. (Marcus)")


def test_a_dual_title_keeps_its_technical_claim():
    assert ranking.looks_non_technical("Chief Executive Officer")
    assert not ranking.looks_non_technical("President, Market Technology")
    assert not ranking.looks_non_technical("Head of Infrastructure")


def test_a_search_url_is_worse_than_no_url():
    profile = "https://www.linkedin.com/in/annika"
    search = "https://www.linkedin.com/search/results/people/?keywords=northgate"
    company = "https://www.linkedin.com/company/northgate"

    assert ranking.is_profile_url(profile)
    assert not ranking.is_profile_url(search)
    assert not ranking.is_profile_url(company)
    # Named separately because canon records these reaching Lusha as a match key.
    assert ranking.is_search_url(search)
    assert ranking.is_search_url(company)
    assert not ranking.is_search_url(profile)

    assert ranking.actionability(row(linkedin_url=search)) < ranking.actionability(row(linkedin_url=""))


def test_persona_tiers_follow_the_call_corpus():
    # Architects convert best; the evaluator is where an account is entered; the
    # economic buyer comes later. That order is the finding, not a preference.
    assert ranking.persona_tier("Network Architect") == 3
    assert ranking.persona_tier("Timing Engineer") == 2
    assert ranking.persona_tier("Chief Technology Officer") == 1
    assert ranking.persona_tier("Head of Catering") == 0
    assert ranking.persona_tier("Solutions Architect") > ranking.persona_tier("CTO")


def test_hedging_is_detected_in_the_match_reason():
    assert ranking.speculates("This appears to be the right person.")
    assert ranking.speculates("Unverified, but plausible.")
    assert not ranking.speculates("Named on the leadership page as owning sync.")


# ── The order ───────────────────────────────────────────────────────────────

def test_the_coarse_tier_still_dominates():
    # A flawless context-only mention must not outrank a weak confirmed profile:
    # the tie-break can reorder within a tier, never across one.
    context = row(recommended_path="campaign_context", confidence="high")
    direct = row(
        recommended_path="linkedin_direct", confidence="low",
        job_title="Head of Catering", linkedin_url="", company_domain="",
        match_reason="Appears to be involved, unverified.",
    )
    assert ranking.sort_key(direct) > ranking.sort_key(context)


def test_the_tie_that_used_to_be_arbitrary_is_now_broken():
    # Identical path and confidence — the old score gave both 33 and fell back to
    # whatever order the provider emitted.
    architect = row(job_title="Network Architect")
    catering = row(job_title="Head of Catering", company_domain="", match_reason="May be relevant.")

    assert ranking.intent_score(architect) == ranking.intent_score(catering)
    assert ranking.sort_key(architect) > ranking.sort_key(catering)


def test_rank_orders_and_stamps():
    weak = row(job_title="Head of Catering", company_domain="", match_reason="Might be relevant.")
    strong = row(job_title="Solutions Architect")
    ordered = ranking.rank([weak, strong])

    assert [p["job_title"] for p in ordered] == ["Solutions Architect", "Head of Catering"]
    # Both numbers are stamped: Fit is what the table shows, actionability is
    # what explains two rows with the same Fit sitting in the order they do.
    assert all("intent_score" in p and "actionability" in p for p in ordered)


def test_ranking_never_drops_or_duplicates_anyone():
    rows = [row(full_name=f"Person {i}", linkedin_url=f"https://linkedin.com/in/p{i}") for i in range(15)]
    ordered = ranking.rank(rows)

    assert len(ordered) == 15
    assert {p["full_name"] for p in ordered} == {f"Person {i}" for i in range(15)}


def test_a_missing_title_does_not_raise():
    # Discovery has returned rows with no title at all; ranking has to survive it.
    assert ranking.actionability(row(job_title=None)) is not None
    assert ranking.persona_tier(None) == 0
    assert not ranking.looks_non_technical(None)
