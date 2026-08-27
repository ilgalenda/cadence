"""The rubric behind the live X-ray evaluation, tested deterministically.

The eval in `test_xray_quality.py` only runs when `XRAY_EVAL=1`, so its scoring
functions would otherwise never be exercised. That is the wrong way round: a
rubric that is silently wrong is worse than no rubric, because it reports a score
either way. These tests always run and cost nothing — they pin the judgements
against the exact rows that motivated each rule.

Every case here is a row shape actually observed in a live run.
"""
from __future__ import annotations

import pytest

from tests.test_xray_quality import (
    LINKEDIN_PROFILE,
    CompanyScore,
    _aggregate,
    _is_infrastructure_error,
    _is_usable_name,
    _looks_non_technical,
    _meets,
    _ratio,
    judged_scores,
)


# --- name usability --------------------------------------------------------

@pytest.mark.parametrize("name", ["Ada Lovelace", "Gustaf von Boisman", "Tal Cohen"])
def test_full_names_are_usable(name):
    assert _is_usable_name(name)


@pytest.mark.parametrize("name", [
    "Xule Z. (Marcus)",   # observed live: truncated LinkedIn display name
    "Alan T.",
    "Alan T",
    "Madonna",            # one token cannot be verified against a company
    "",
    "   ",
])
def test_truncated_or_single_names_are_not_usable(name):
    assert not _is_usable_name(name)


# --- profile URL integrity -------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/in/gustafvb/",
    "http://linkedin.com/in/tal-cohen-85a2911",
    "https://uk.linkedin.com/in/someone",
])
def test_real_member_profiles_are_accepted(url):
    assert LINKEDIN_PROFILE.match(url)


@pytest.mark.parametrize("url", [
    "https://www.benzinga.com/events/fintech-awards/company/northgate/",  # observed live
    "https://www.linkedin.com/company/northgate/",   # a company page is not a person
    "https://linkedin.com/in/",                   # no member slug
    "",
])
def test_non_profile_urls_are_rejected(url):
    assert not LINKEDIN_PROFILE.match(url)


# --- ICP fit ---------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Chair and Chief Executive Officer",             # observed live
    "EVP & President, European Market Services",     # observed live
    "Chief Regulatory Officer",
    "Head of Investor Relations",
    "General Counsel",
])
def test_senior_non_technical_titles_miss_the_icp(title):
    assert _looks_non_technical(title)


@pytest.mark.parametrize("title", [
    "Head of Infrastructure",
    "Network Engineer Sr Specialist",
    "SVP, Head of Capital Markets Technology",
    "Head of Trading Technology",
    "Chief Architect",
    "Site Reliability Engineering Lead",
])
def test_targeted_technical_titles_fit_the_icp(title):
    assert not _looks_non_technical(title)


def test_a_dual_title_keeps_its_technical_claim():
    """"President, Market Technology" is a technology remit, not a figurehead.

    This is why the rule is not a plain blocklist: the exclusion only applies
    when *no* technical term appears alongside it.
    """
    assert not _looks_non_technical("President, Market Technology")
    assert not _looks_non_technical("Chief Executive Officer and CTO")


# --- rate arithmetic -------------------------------------------------------

def test_nothing_to_judge_scores_perfect_not_zero():
    """A company with no linkedin_direct rows has not failed URL integrity.

    Scoring an empty denominator as 0.0 would drag the aggregate below the floor
    and report a regression that did not happen.
    """
    assert _ratio(0, 0) == 1.0


def test_aggregate_reports_the_defects_it_counted():
    """One clean company and one full of the observed defects."""
    clean = CompanyScore(
        company="Good", error=None, rows=8, outreach_rows=5,
        outreach_claiming_linkedin=5,
    )
    dirty = CompanyScore(
        company="Bad", error=None, rows=4, outreach_rows=4,
        outreach_claiming_linkedin=2, bad_profile_urls=2,
        unusable_names=1, hedged=2, icp_misses=3, duplicates=1, missing_domain=4,
    )

    agg = _aggregate([clean, dirty])

    assert agg["error_rate"] == 0.0
    assert agg["yield"] == 6.0                      # (8 + 4) / 2
    assert agg["outreach_yield"] == 4.5             # (5 + 4) / 2
    assert agg["profile_url_integrity"] == pytest.approx(5 / 7)
    assert agg["name_usability"] == pytest.approx(11 / 12)
    assert agg["speculation_rate"] == pytest.approx(2 / 12)
    assert agg["icp_fit_rate"] == pytest.approx(6 / 9)
    assert agg["dup_rate"] == pytest.approx(1 / 12)
    assert agg["domain_coverage"] == pytest.approx(8 / 12)


def test_an_errored_company_counts_against_the_error_rate():
    scores = [
        CompanyScore(company="Ok", error=None, rows=7, outreach_rows=4),
        CompanyScore(company="Broke", error="no_results"),
    ]
    assert _aggregate(scores)["error_rate"] == 0.5


# --- floor direction -------------------------------------------------------

def test_floors_compare_in_the_right_direction():
    """A "lower is better" metric must not be judged as if higher were better.

    Getting this backwards is the failure that would make the whole harness
    report success on its worst run.
    """
    assert _meets("icp_fit_rate", 0.95) and not _meets("icp_fit_rate", 0.5)
    assert _meets("speculation_rate", 0.0) and not _meets("speculation_rate", 0.5)
    assert _meets("error_rate", 0.0) and not _meets("error_rate", 0.2)
    assert _meets("yield", 9.0) and not _meets("yield", 2.0)


# --- attributing a failure to the right cause ------------------------------

@pytest.mark.parametrize("error", [
    "web_search: api_error: Connection error.",   # observed live
    "api_error: overloaded_error",
    "web_search: api_error: Request timeout",
])
def test_provider_faults_are_not_quality_failures(error):
    """A dropped connection says nothing about the shortlist X-ray would build."""
    assert _is_infrastructure_error(error)


@pytest.mark.parametrize("error", [
    "web_search: parse_failed: could not parse JSON array from model output",
    "no_results",
    "no_enabled_sources",
    None,
])
def test_agent_outcomes_are_judged(error):
    """These ran and produced nothing usable — precisely what to measure."""
    assert not _is_infrastructure_error(error)


def test_unreachable_companies_are_excluded_from_the_scores():
    """A company that never reached the provider must not drag the yield down.

    Two good companies and one dropped connection should score as two good
    companies, not as a third of a catastrophe.
    """
    scores = [
        CompanyScore(company="A", error=None, rows=8, outreach_rows=5),
        CompanyScore(company="B", error=None, rows=6, outreach_rows=4),
        CompanyScore(company="C", error="web_search: api_error: Connection error."),
    ]

    assert [s.company for s in judged_scores(scores)] == ["A", "B"]

    agg = _aggregate(scores)
    assert agg["error_rate"] == 0.0        # not 1/3
    assert agg["yield"] == 7.0             # (8 + 6) / 2, not / 3


def test_a_company_that_ran_and_found_nothing_still_counts_against_the_score():
    """`parse_failed` is X-ray's problem, so it stays in the denominator."""
    scores = [
        CompanyScore(company="A", error=None, rows=8, outreach_rows=5),
        CompanyScore(company="B", error="web_search: parse_failed: ...", rows=0),
    ]
    agg = _aggregate(scores)
    assert agg["error_rate"] == 0.5
    assert agg["yield"] == 4.0
