"""The quality bar for X-ray discovery — a live, opt-in evaluation.

The rest of the suite mocks the SDK, so it proves the *shape* of a request and the
determinism of the transformation, and can say nothing about whether the people
X-ray returns are any good. That gap is why a change of web_search tool
generation once collapsed the shortlist from fifteen people to two without a
single test going red.

This module closes it by running real searches against real companies and scoring
the rows. It never runs in the normal suite — the ordinary run must stay fast,
free and deterministic — and follows the opt-in convention already set by the
live Lusha smoke test in `test_enrichment.py`.

    Run: XRAY_EVAL=1 python3 -m pytest tests/test_xray_quality.py -s

Cost: one Sonnet web-search turn per company, roughly $0.30 and 60-120s each.

**What this can and cannot judge.** Field integrity, name usability, duplication,
hedging and yield are mechanical, so they are measured exactly. ICP fit is scored
against a title lexicon, which is a smoke alarm and not a judgement: it will
misread an unusual title in either direction. Whether a person is genuinely worth
approaching, and whether a revealed email is *correct*, are not automatable and
remain Sam's call.

**Privacy.** Only aggregate numbers are ever written to disk. Discovered people
are real individuals; their names and profile URLs stay in the terminal and never
reach a baseline file or the repo.
"""
from __future__ import annotations

import json
import os
import re
import statistics
from dataclasses import dataclass, field

import pytest
from dotenv import dotenv_values

from agents.mind import client as mind_client
from agents.sales.xray import agent
from paths import REPO_ROOT, data_root

pytestmark = pytest.mark.skipif(
    not os.getenv("XRAY_EVAL"),
    reason="set XRAY_EVAL=1 to run the live X-ray quality evaluation (spends API budget)",
)


@pytest.fixture(autouse=True)
def anthropic_key(monkeypatch):
    """Real credentials — this module is the one that deliberately calls the API.

    Overrides the suite-wide autouse fixture that stamps a placeholder key on
    every test. Left in place, that placeholder makes all five companies fail
    instantly with an auth error, which the harness would then report as a
    finding about X-ray rather than about its own setup — a measurement that
    lies is worse than no measurement.

    The key is read straight from `.env` rather than via `load_dotenv`, because
    other test modules `setdefault` a placeholder at import time and the real
    value must win over it without disturbing anything else in the environment.
    """
    key = (dotenv_values(REPO_ROOT / ".env") or {}).get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("no ANTHROPIC_API_KEY in backend/.env — cannot run the live evaluation")

    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    # The Mind holds one process-wide client, which may already have been built
    # with the placeholder by an earlier test.
    mind_client._reset_client_for_tests()
    yield
    mind_client._reset_client_for_tests()

# One company per Acme vertical, plus a deliberately unglamorous one. A set of
# only famous names would flatter the agent: household companies have dense public
# footprints, and the hard case for discovery is a mid-size firm whose engineers
# barely appear in search results.
COMPANIES = [
    "Northgate Nordics",     # exchange / capital markets
    "Jump Trading",         # prop trading / HFT
    "Telefónica Germany",   # telecom / 5G
    "Equinix",              # data centre / colocation
    "Sky Italia",           # broadcast — thinner public engineering footprint
]

OUTREACH_TIERS = {"linkedin_direct", "email_enrichment"}

# A genuine LinkedIn member profile. `linkedin.com/company/...` and news articles
# are not profiles, and a row claiming linkedin_direct on one cannot be actioned.
LINKEDIN_PROFILE = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/\s]+", re.I)

# Titles the ICP actually targets (see XRAY_SYSTEM_PROMPT).
ICP_TITLE_TERMS = [
    "infrastructure", "network", "trading technology", "low latency", "low-latency",
    "electronic trading", "market data", "compliance technology", "surveillance",
    "regtech", "time sync", "timing", "frequency", "ptp", "gnss", "cto",
    "chief technology", "architect", "principal engineer", "site reliability",
    "platform", "engineering", "engineer", "technology", "technical", "operations",
]

# Senior but non-technical: legitimate context, never an outreach target unless the
# title also carries a technology remit. Sam's call, 2026-08-05.
NON_TECHNICAL_TERMS = [
    "chief executive", "ceo", "president", "chair", "board", "investor relations",
    "general counsel", "legal", "chief financial", "cfo", "chief regulatory",
    "chief compliance", "human resources", "marketing", "communications", "sales",
]

# Phrases a model reaches for when it is guessing. A row that hedges about its own
# central claim is context at best, and must not be sold as a verified contact.
HEDGE_MARKERS = [
    "needs verification", "need verification", "unverified", "plausible",
    "appears to be", "may be", "might be", "unclear", "presumably", "likely holds",
    "cannot confirm", "not confirmed", "assumed",
]


@dataclass
class CompanyScore:
    """The measurements for one company's shortlist."""

    company: str
    error: str | None
    rows: int = 0
    outreach_rows: int = 0
    bad_profile_urls: int = 0
    outreach_claiming_linkedin: int = 0
    unusable_names: int = 0
    hedged: int = 0
    icp_misses: int = 0
    duplicates: int = 0
    missing_domain: int = 0
    offenders: list[str] = field(default_factory=list)


def _is_usable_name(name: str) -> bool:
    """Two real name parts. `Xule Z. (Marcus)` cannot be addressed or verified.

    A parenthesised nickname is dropped before judging, because it is not part of
    the legal name and it hides the very truncation being looked for — the
    observed row was `Xule Z. (Marcus)`, whose surname is a bare initial.
    """
    stripped = re.sub(r"\([^)]*\)", " ", name)
    parts = [p for p in re.split(r"\s+", stripped.strip()) if p]
    if len(parts) < 2:
        return False
    # A trailing initial ("Alan T.", "Alan T") is a truncated display name.
    return not re.fullmatch(r"[A-Za-z]\.?", parts[-1])


def _looks_non_technical(title: str) -> bool:
    """True when the title is senior-but-non-technical with no technology remit."""
    low = title.lower()
    if not any(term in low for term in NON_TECHNICAL_TERMS):
        return False
    # A dual title ("President, Market Technology") keeps its technical claim.
    return not any(term in low for term in ICP_TITLE_TERMS)


def _score_company(company: str) -> CompanyScore:
    out = agent.shortlist("eval", {"company": company}, None, None)
    rows = out["results"]
    score = CompanyScore(company=company, error=out["error"], rows=len(rows))

    seen: set[str] = set()
    for row in rows:
        title = row.get("job_title") or ""
        name = row.get("full_name") or ""
        url = row.get("linkedin_url") or ""
        path = row.get("recommended_path") or ""
        reason = (row.get("match_reason") or "").lower()

        identity = (url or name).lower()
        if identity in seen:
            score.duplicates += 1
        seen.add(identity)

        if not _is_usable_name(name):
            score.unusable_names += 1
            score.offenders.append(f"name: {name!r}")

        if any(marker in reason for marker in HEDGE_MARKERS):
            score.hedged += 1
            score.offenders.append(f"hedged: {name!r}")

        if not row.get("company_domain"):
            score.missing_domain += 1

        if path in OUTREACH_TIERS:
            score.outreach_rows += 1
            if _looks_non_technical(title):
                score.icp_misses += 1
                score.offenders.append(f"non-ICP: {name!r} — {title!r}")

        if path == "linkedin_direct":
            score.outreach_claiming_linkedin += 1
            if not LINKEDIN_PROFILE.match(url):
                score.bad_profile_urls += 1
                score.offenders.append(f"bad profile url: {name!r} — {url!r}")

    return score


def _ratio(good: int, total: int) -> float:
    """A rate, where "nothing to judge" scores perfect rather than zero."""
    return 1.0 if total == 0 else good / total


# A company that never reached the model tells us nothing about X-ray's quality.
# Counting a dropped connection as a failed shortlist would blame the agent for
# the weather, and — worse — drag the yield toward zero so a clean run looks like
# a regression.
INFRASTRUCTURE_ERRORS = ("connection error", "api_error", "overloaded", "timeout", "rate limit")


def _is_infrastructure_error(error: str | None) -> bool:
    return bool(error) and any(marker in str(error).lower() for marker in INFRASTRUCTURE_ERRORS)


def judged_scores(scores: list[CompanyScore]) -> list[CompanyScore]:
    """The companies whose result is attributable to X-ray.

    A `parse_failed` or `no_results` company stays in — it ran and produced
    nothing, which is exactly the kind of failure worth measuring. Only the ones
    that never got an answer out of the provider are set aside.
    """
    return [s for s in scores if not _is_infrastructure_error(s.error)]


def _aggregate(scores: list[CompanyScore]) -> dict[str, float]:
    scores = judged_scores(scores)
    total_rows = sum(s.rows for s in scores)
    outreach = sum(s.outreach_rows for s in scores)
    claiming = sum(s.outreach_claiming_linkedin for s in scores)
    return {
        "error_rate": sum(1 for s in scores if s.error) / len(scores),
        "yield": statistics.mean([s.rows for s in scores]),
        "outreach_yield": statistics.mean([s.outreach_rows for s in scores]),
        "profile_url_integrity": _ratio(claiming - sum(s.bad_profile_urls for s in scores), claiming),
        "name_usability": _ratio(total_rows - sum(s.unusable_names for s in scores), total_rows),
        "speculation_rate": 1.0 - _ratio(total_rows - sum(s.hedged for s in scores), total_rows),
        "icp_fit_rate": _ratio(outreach - sum(s.icp_misses for s in scores), outreach),
        "domain_coverage": _ratio(total_rows - sum(s.missing_domain for s in scores), total_rows),
        "dup_rate": 1.0 - _ratio(total_rows - sum(s.duplicates for s in scores), total_rows),
    }


# Floors, not equalities: run-to-run spread is real (one company measured 8, 8, 10
# rows on three consecutive runs), so an exact expectation would flap.
FLOORS = {
    "error_rate": ("<=", 0.0),
    "yield": (">=", 6.0),
    "outreach_yield": (">=", 3.0),
    "profile_url_integrity": (">=", 1.0),
    "name_usability": (">=", 0.90),
    "speculation_rate": ("<=", 0.10),
    "icp_fit_rate": (">=", 0.80),
    "domain_coverage": (">=", 0.80),
    "dup_rate": ("<=", 0.0),
}


def _meets(name: str, value: float) -> bool:
    comparator, bound = FLOORS[name]
    return value <= bound if comparator == "<=" else value >= bound


def _baseline_path():
    """Aggregates only, and outside the repo — see the module docstring."""
    return data_root() / "eval" / "xray-baseline.json"


def _load_baseline() -> dict:
    path = _baseline_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_baseline(aggregate: dict[str, float]) -> None:
    path = _baseline_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(aggregate, indent=2, sort_keys=True), encoding="utf-8")


def test_xray_discovery_quality(capsys):
    """Score live shortlists across the vertical set and report against the floors."""
    scores = [_score_company(company) for company in COMPANIES]

    # Every company failing is almost never a fact about X-ray — it is a missing
    # key, no network, or a provider outage. Saying so beats reporting a score of
    # zero, which reads as a catastrophic quality regression and sends the next
    # person to debug the prompt.
    if all(s.error for s in scores):
        raise AssertionError(
            "every company errored — treat this as a harness/setup fault, not a "
            f"quality result. Errors: {sorted({str(s.error) for s in scores})}"
        )

    # Too few companies actually reached the model to say anything with a straight
    # face. Better to report thin evidence than to average three numbers and call
    # it a quality bar.
    judged = judged_scores(scores)
    unreachable = [s for s in scores if s not in judged]
    if len(judged) < 3:
        raise AssertionError(
            f"only {len(judged)} of {len(scores)} companies reached the provider — "
            "too little signal to judge quality. Retry when the API is healthy. "
            f"Unreachable: {[(s.company, s.error) for s in unreachable]}"
        )

    aggregate = _aggregate(scores)
    baseline = _load_baseline()

    with capsys.disabled():
        print("\n\nX-ray discovery quality\n" + "=" * 78)
        print(f"{'company':24} {'rows':>5} {'reach':>6} {'badURL':>7} {'name':>5} {'hedge':>6} {'nonICP':>7}")
        for s in scores:
            print(
                f"{s.company[:24]:24} {s.rows:>5} {s.outreach_rows:>6} "
                f"{s.bad_profile_urls:>7} {s.unusable_names:>5} {s.hedged:>6} {s.icp_misses:>7}"
                + ("   ERROR: " + str(s.error) if s.error else "")
            )

        print("\n" + "-" * 78)
        print(f"{'metric':24} {'now':>8} {'floor':>8} {'baseline':>10} {'delta':>8}   verdict")
        for name, value in aggregate.items():
            comparator, bound = FLOORS[name]
            was = baseline.get(name)
            delta = "" if was is None else f"{value - was:+.2f}"
            print(
                f"{name:24} {value:>8.2f} {comparator + str(bound):>8} "
                f"{'—' if was is None else f'{was:.2f}':>10} {delta:>8}   "
                f"{'ok' if _meets(name, value) else 'BELOW FLOOR'}"
            )

        if unreachable:
            print(
                f"\nNot judged ({len(unreachable)} never reached the provider, "
                "excluded from the scores above):"
            )
            for s in unreachable:
                print(f"  - {s.company}: {s.error}")

        offenders = [o for s in judged for o in s.offenders]
        if offenders:
            print("\nRows to eyeball (not written to disk):")
            for offender in offenders[:20]:
                print("  -", offender)

        failed = {name: value for name, value in aggregate.items() if not _meets(name, value)}

        # A baseline is a claim about what good looks like, so only a run that
        # clears every floor is allowed to set one. Recording a failing run would
        # quietly move the goalposts down and make the next regression invisible.
        if baseline:
            print(f"\nBaseline at {_baseline_path()}. Delete it to re-baseline.")
        elif failed:
            print("\nNo baseline written — this run is below its floors, so it is not a bar to hold.")
        else:
            _save_baseline(aggregate)
            print(f"\nBaseline written to {_baseline_path()} (aggregates only).")

    assert not failed, f"below floor: {failed}"
