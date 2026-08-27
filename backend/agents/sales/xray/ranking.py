"""How a shortlist is ordered, and the judgements that order it.

X-ray casts a deliberately wide net — up to fifteen people, most of whom will not
be approached. That is the right shape for discovery, but it puts the whole
weight of the agent's usefulness on the *order*: nobody reads row twelve, so a
strong name that lands there has not been found.

The ranking this replaces could not carry that weight. It was::

    path_weight * 10 + confidence_weight        # 3 paths x 3 levels

which is nine distinct values spread across fifteen rows. Half a shortlist tied,
and ties fell back to the order the provider happened to emit — so the head of
the list, the only part anyone reads, was in practice unranked. A wide net whose
top is arbitrary returns exactly what "mixed results" describes.

So the coarse tier is kept — a confirmed profile ready for outreach really does
beat a context-only mention, however confident the mention was — and the tie is
broken by things already on the row:

  * a genuine ``/in/`` profile URL, because it is the difference between a person
    you can reach and a person a page mentioned;
  * the persona tier the title belongs to, weighted by which tier converts. This
    comes from Acme's own call corpus, not from taste: architects and
    technical decision-makers carry the conversations that close, and the
    engineer tier is where an account is entered;
  * a ``company_domain``, because enrichment matches on it — a row without one is
    a row whose email probably cannot be bought;
  * against: hedging in the match reason, and a senior-but-non-technical title.

**These predicates are also the eval's rubric.** They live here rather than in
`tests/test_xray_quality.py` so the harness grades against the same definitions
the agent ranks by. The circularity that would create is bounded deliberately:
the harness's ICP-fit metric is computed from the title lexicon alone, which is
independent of the path, URL and domain signals doing most of the tie-breaking.
"""
from __future__ import annotations

import re

# ── Shared vocabulary ───────────────────────────────────────────────────────

LINKEDIN_PROFILE = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/\s]+", re.I)

# A LinkedIn URL that is not a person. Canon records these reaching Lusha as a
# match key, which both wastes credit and corrupts dedupe, so they are worth
# naming rather than merely failing the profile test.
NON_PROFILE_LINKEDIN = re.compile(r"linkedin\.com/(search|company|pub/dir|jobs)/", re.I)

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

# The persona tiers, from `canon/gtm/sales-navigator-search-strings.md`, which
# sharpened them against 531 recorded calls. The order is the finding: tier 2
# architects "converts best", and an account is entered on the tier 1 evaluator.
# The economic buyer comes later in the cycle, so it ranks below both.
PERSONA_TIERS: list[tuple[int, list[str]]] = [
    (3, [  # architects and technical decision-makers — the real champions
        "network architect", "solution architect", "solutions architect",
        "chief architect", "head of architecture", "systems architect",
        "design authority", "head of infrastructure", "head of network",
        "head of engineering", "head of low latency", "technical director",
        "director of engineering", "principal engineer",
    ]),
    (2, [  # the technical evaluator — where an account is entered
        "network engineer", "systems engineer", "system engineer",
        "synchronisation engineer", "synchronization engineer", "timing engineer",
        "transmission engineer", "broadcast engineer", "rf engineer",
        "fpga engineer", "platform engineer", "infrastructure engineer",
        "reliability engineer", "design engineer",
    ]),
    (1, [  # the economic buyer — later in the cycle
        "cto", "chief technology officer", "cio", "chief information officer",
        "vp engineering", "vp of engineering", "vp infrastructure",
        "director of it", "head of technology", "chief engineer",
    ]),
]

_PATH_WEIGHT = {"linkedin_direct": 3, "email_enrichment": 2, "campaign_context": 1}
_CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}


# ── Judgements ──────────────────────────────────────────────────────────────

def is_usable_name(name: str) -> bool:
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


def looks_non_technical(title: str) -> bool:
    """True when the title is senior-but-non-technical with no technology remit."""
    low = (title or "").lower()
    if not any(term in low for term in NON_TECHNICAL_TERMS):
        return False
    # A dual title ("President, Market Technology") keeps its technical claim.
    return not any(term in low for term in ICP_TITLE_TERMS)


def matches_icp_title(title: str) -> bool:
    """True when the title reads as somebody who could own timing."""
    return any(term in (title or "").lower() for term in ICP_TITLE_TERMS)


def speculates(match_reason: str) -> bool:
    """True when the row hedges about its own central claim."""
    low = (match_reason or "").lower()
    return any(marker in low for marker in HEDGE_MARKERS)


def is_profile_url(url: str) -> bool:
    """True for a genuine personal profile, not a search or company page."""
    return bool(LINKEDIN_PROFILE.match((url or "").strip()))


def is_search_url(url: str) -> bool:
    """True for a LinkedIn URL that is not a person at all."""
    return bool(NON_PROFILE_LINKEDIN.search(url or ""))


def persona_tier(title: str) -> int:
    """Which persona tier the title belongs to, 3 highest, 0 for none."""
    low = (title or "").lower()
    for weight, terms in PERSONA_TIERS:
        if any(term in low for term in terms):
            return weight
    return 0


# ── The score ───────────────────────────────────────────────────────────────

def intent_score(row: dict) -> int:
    """The coarse tier: outreach path dominates, confidence breaks it.

    Kept as its own function and its own number because it is what the page and
    the shortlist store already show as `Fit`, and because it is the part of the
    ranking that is a *judgement about the person* rather than about how well the
    row was filled in.
    """
    path = _PATH_WEIGHT.get(row.get("recommended_path"), 1)
    confidence = _CONFIDENCE_WEIGHT.get(row.get("confidence"), 1)
    return path * 10 + confidence


def actionability(row: dict) -> int:
    """The tie-break: how much of this row can actually be acted on.

    Bounded to roughly ±10 so it can only reorder within a coarse tier, never
    lift a context-only mention above a confirmed profile. The tier is the
    judgement; this is the evidence behind it.
    """
    title = row.get("job_title") or ""
    score = 0
    if is_profile_url(row.get("linkedin_url") or ""):
        score += 3
    elif is_search_url(row.get("linkedin_url") or ""):
        # Worse than no URL: it looks like a contact and poisons enrichment.
        score -= 2
    score += persona_tier(title)
    if (row.get("company_domain") or "").strip():
        score += 1
    if speculates(row.get("match_reason") or ""):
        score -= 3
    if looks_non_technical(title):
        score -= 4
    if not is_usable_name(row.get("full_name") or ""):
        score -= 2
    return score


def sort_key(row: dict) -> tuple[int, int]:
    """Order a shortlist: coarse tier first, evidence second."""
    return (intent_score(row), actionability(row))


def rank(rows: list[dict]) -> list[dict]:
    """Sort in place-safe fashion and stamp each row with what it scored.

    Both numbers are stamped: `intent_score` is what the table shows as Fit, and
    `actionability` is what explains two rows sharing a Fit sitting in the order
    they do.
    """
    ordered = sorted(rows, key=sort_key, reverse=True)
    for row in ordered:
        row["intent_score"] = intent_score(row)
        row["actionability"] = actionability(row)
    return ordered
