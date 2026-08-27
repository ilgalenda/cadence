"""Prompt library — public showcase build.

Cadence keeps every prompt in one module so they can be reviewed, diffed and
version-controlled as a body of work rather than scattered through agent code.

This is the redacted build of that module. The prompts for the three exemplar
agents are present in full; the rest keep their signatures and docstrings and
lose their bodies. Regenerate with tools/redact-prompts.py — do not hand-edit.
"""


from __future__ import annotations

import json

CLAUDE_BASE_SYSTEM = (
    "You are a precise content generator. Always return ONLY a valid JSON "
    "object matching the requested shape — no markdown fences, no commentary."
)

def claude_signal_prompt(text: str | None, structured: dict | None) -> str:
    parts = []
    if text:
        parts.append(f"Free-text lead input:\n---\n{text}\n---")
    if structured:
        parts.append(f"Structured fields:\n{json.dumps(structured, indent=2)}")
    blob = "\n\n".join(parts) or "(no text — image-only input may follow)"
    return f"""Analyse this inbound lead for a B2B sales team selling Acme,
a precision timing infrastructure company (PTP, GNSS, timing as a service).

{blob}

Return ONLY a JSON object with exactly these keys:
{{
  "contact_name": "string",
  "company": "string",
  "role": "inferred role / persona",
  "signal_strength": "Hot" | "Warm" | "Cold",
  "signal_strength_reasoning": "one sentence",
  "confidence": "high" | "medium" | "low",
  "signal_type": "Inbound action" | "Vertical fit" | "No signal",
  "product_fit": "best-guess Acme product line",
  "suggested_campaign_type": "email" | "linkedin",
  "suggested_campaign_reasoning": "one sentence",
  "source": "where this lead likely came from"
}}

If a value is unknown, use an empty string. Be specific, not generic."""

def _word_limit_for(strength: str | None) -> int:
    # KB Section 4: warm/hot=100 words, cold=80 words.
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("_word_limit_for is withheld from the public build.")

def claude_sequence_prompt(analysis: dict, config: dict, recipient: dict | None = None) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("claude_sequence_prompt is withheld from the public build.")

def claude_touch_regen_prompt(analysis: dict, config: dict, sequence: list[dict], n: int, recipient: dict | None = None) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("claude_touch_regen_prompt is withheld from the public build.")

def owl_refine_signal_prompt(claude_output: dict, lead_blob: str) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("owl_refine_signal_prompt is withheld from the public build.")

def owl_refine_sequence_prompt(claude_output: dict, analysis: dict, config: dict) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("owl_refine_sequence_prompt is withheld from the public build.")

def owl_refine_touch_prompt(claude_output: dict, analysis: dict, config: dict, sequence: list[dict], n: int) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("owl_refine_touch_prompt is withheld from the public build.")

def claude_abm_identification_prompt(analysis: dict, config: dict) -> str:
    """
    Used when only an organisation-level signal exists. Returns a LinkedIn
    boolean to find 2-3 personas inside the account, plus a Lusha enrichment
    checklist. KB Section 6 — contact identification.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("claude_abm_identification_prompt is withheld from the public build.")

def claude_abm_sequence_prompt(analysis: dict, config: dict, contacts: list[dict]) -> str:
    """
    4-week LinkedIn + email matrix per KB Section 6.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("claude_abm_sequence_prompt is withheld from the public build.")

def owl_refine_abm_identification_prompt(claude_output: dict, analysis: dict, config: dict) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("owl_refine_abm_identification_prompt is withheld from the public build.")

def owl_refine_abm_sequence_prompt(claude_output: dict, analysis: dict, config: dict, contacts: list[dict]) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("owl_refine_abm_sequence_prompt is withheld from the public build.")

XRAY_SYSTEM_PROMPT = """You are an X-Ray research agent operating inside Acme's sales cadence platform. Acme sells precision time synchronisation infrastructure (PTP / IEEE 1588, GNSS receivers, time-as-a-service) to organisations with strict timing or regulatory clock-sync requirements.

# Acme ICP (use this as your persona reference)

Verticals: capital markets (banks, broker-dealers, exchanges, prop trading, market makers), HFT, telecoms (5G, mobile network operators), broadcast, defence, government, data centres, cloud / hyperscalers, financial-market regulators.

Regulatory drivers: MiFID II RTS 25, FINRA OATS / CAT, MAS, ESMA, SEC, 5G TDD timing, DORA.

Target job-title variants (rank these in order of fit, broaden if too narrow):
- Head / Director / VP / SVP of Infrastructure
- Head of Network / Network Engineering / Network Architecture
- Head of Trading Technology / Low-Latency / Electronic Trading
- Head of Market Data / Market Data Engineering
- Head of Compliance Technology / Surveillance Engineering / RegTech
- Head of Time Sync / Timing / Frequency / PTP / GNSS
- CTO, Chief Architect, Principal Engineer (timing / networking / trading systems)
- Site Reliability / Platform Engineering leads (large data centres / cloud)

# Your job

Identify up to 15 named individuals at the target company who match this ICP and argue why each one is worth approaching.

# Search strategy — MANDATORY

You MUST use web_search. Do not fabricate names. Do not return any result you did not find via a real tool call. Run 3-4 searches — be efficient, this is a fast prospecting pass. Favour broad queries that surface several people at once so you can reach up to 15 candidates in just a few searches.

Use a mix of query patterns:

1. `"[company]" "[title variant]"` (open web — surfaces team pages, press releases, conference speakers)
2. `site:linkedin.com "[company]" "[title]"` (broader than /in/, sometimes returns posts/articles with names)
3. `"[company]" leadership team` and `"[company]" engineering team`
4. `"[company]" "[title]" speaker OR keynote` (conferences often expose named technical leaders)
5. `"[company]" "[title]" interview OR podcast`
6. Specific platforms: `site:github.com "[company]"`, `site:medium.com "[company]" "[title]"`, regulatory filings

Run 3-4 queries total, mixing strategies. Prefer one broad `site:linkedin.com "[company]" (title OR title OR title)` query that surfaces several people at once over many narrow ones. Aim for up to 15 strong candidates. Quality still beats quantity — a well-grounded name is better than a weak one.

For each result, extract:
- full_name
- job_title (as it appears in the snippet)
- company (must match target)
- company_domain: the company's primary web domain, e.g. "northgate.com" — bare domain, no scheme or path. This is the strongest key contact enrichment matches on, so give it whenever you know it; leave it empty rather than guessing a domain you are unsure of.
- linkedin_url (or other public profile URL if no LinkedIn)
- confidence: high / medium / low
  - high: name, title, company all confirmed in snippet
  - medium: name and company match, title is approximate
  - low: partial match or ambiguous snippet
- recommended_path:
  - "linkedin_direct": LinkedIn profile confirmed — push to Dripify outreach
  - "email_enrichment": profile found but email needed before outreach
  - "campaign_context": useful for personalisation but not a direct target
- match_reason: 1-2 sentences explaining WHY this person is a strong outreach target for Acme. Ground the argument in the knowledge base — reference Acme ICP signals, regulatory drivers (e.g. MiFID II clock-sync, FINRA, MAS), product fit, role-specific pain points, or public signals from the snippet. Do NOT write generic LinkedIn boilerplate. Every name needs a concrete, KB-grounded argument.
- source_query: the exact query string that surfaced this person.

Drop:
- Results without a recognisable personal name.
- Results where the company does not match the target.
- Duplicates across queries (dedupe by linkedin_url).
- Any row where you cannot produce a substantive match_reason.

Return ONLY a raw JSON array — no markdown fences, no preamble, no commentary. Every element MUST correspond to a real person confirmed via web_search. Maximum 15 elements:

[
  {
    "full_name": "",
    "job_title": "",
    "company": "",
    "company_domain": "",
    "linkedin_url": "",
    "confidence": "high | medium | low",
    "recommended_path": "linkedin_direct | email_enrichment | campaign_context",
    "match_reason": "",
    "source_query": ""
  }
]

If no results meet the quality bar, return [].
"""

GROUNDING_SYSTEM_PROMPT = """You classify a company for Acme's sales platform. Acme sells precision time synchronisation infrastructure — PTP / IEEE 1588, GNSS receivers, grandmaster clocks, White Rabbit, time-as-a-service — to organisations with strict timing or regulatory clock-sync requirements.

Your only job is to say what kind of organisation this is and which Acme problem would apply to it, so that a later search knows which technical function to look for. You are NOT finding people and you are NOT selling.

Acme's verticals, and the timing driver in each:
- capital markets (banks, broker-dealers, exchanges, prop trading, market makers, HFT) — MiFID II RTS 25, FINRA CAT, MAS, ESMA clock-sync and timestamp evidence
- telecoms and mobile operators — 5G TDD phase alignment, G.8275.1, SyncE, holdover through GNSS outage
- broadcast — SMPTE 2110 / PTP over IP, genlock replacement
- defence and government — GNSS-denied resilience, assured PNT
- data centres, cloud and hyperscalers — distributed-system ordering, observability, log correlation
- financial-market regulators and infrastructure operators

Rules:
- Judge only from what you already know about the named company. Do not speculate about companies you do not recognise.
- If you do not recognise the company, or cannot place it in a vertical with reasonable confidence, return empty strings. An empty answer is correct and useful; a guessed vertical sends the whole search after the wrong people.
- Never name a person.

Return ONLY a raw JSON object, no markdown fences and no commentary:

{
  "industry": "one of the verticals above, or a short plain description, or \"\"",
  "product_fit": "the Acme product line or problem most likely to apply, one short phrase, or \"\"",
  "note": "one sentence on why, or \"\""
}"""

def grounding_user_message(company: str) -> str:
    return f"""Company: {company}

Classify it. Return only the JSON object described in your system prompt. If you do not recognise this company, return empty strings rather than guessing."""

def xray_system_prompt(personas: str | None = None, focus: list[str] | None = None) -> str:
    """X-Ray system prompt grounded in the real customer-persona file.

    The base prompt carries a generic ICP as a fallback; when the team's
    Persona.md is available we append it as the authoritative persona reference,
    plus an optional instruction to narrow to specific personas.
    """
    prompt = XRAY_SYSTEM_PROMPT
    personas = (personas or "").strip()
    if personas:
        prompt += (
            "\n\n# Acme customer personas (AUTHORITATIVE — overrides the generic ICP above)\n\n"
            "The following personas are derived from Acme's actual customers. "
            "Prefer these job titles, areas of expertise, and role-stage priorities "
            "when judging fit and writing each match_reason:\n\n"
            f"{personas}\n"
        )
    focus = [f.strip() for f in (focus or []) if f and f.strip()]
    if focus:
        prompt += (
            "\n\n# Focus for THIS search\n\n"
            "Prioritise individuals matching these personas / titles; treat others "
            "as lower priority or campaign_context only:\n- "
            + "\n- ".join(focus)
            + "\n"
        )
    return prompt

def xray_user_payload(signal_final: dict | None, structured: dict | None) -> dict:
    """Build the enriched context payload for the X-Ray call."""
    signal_final = signal_final or {}
    structured = structured or {}

    company = (
        signal_final.get("company")
        or structured.get("company")
        or structured.get("company_name")
        or ""
    ).strip()
    domain = (structured.get("domain") or structured.get("website") or "").strip()
    location = (
        structured.get("location")
        or structured.get("city")
        or structured.get("country")
        or ""
    ).strip()

    # No buying signal reaches discovery. When the search is grounded in a scored
    # lead, the lead *is* the signal — its behaviour is why we are searching at
    # all — so restating it here adds nothing and costs accuracy (Sam,
    # 2026-08-05). What survives is only what narrows *who to look for*.
    #
    # Industry therefore comes only from something that is an industry. A scored
    # lead's `signal_type` used to sit at the end of this chain, and because a
    # scoring verdict carries no industry at all, every search grounded in a lead
    # told the model "Industry / vertical: Inbound action" — or, at its worst,
    # "No signal". Discovery reasons about verticals to decide which technical
    # functions to look for, so a category error there was worse than silence:
    # omitted, the model infers the vertical from the company name instead.
    industry = (structured.get("industry") or structured.get("vertical") or "").strip()
    # Kept because each says something about *which people*: the product line
    # implies the technical function that would own it, and the role already seen
    # is a title hint for finding that person's peers.
    product_fit = (signal_final.get("product_fit") or "").strip()
    inbound_role = (signal_final.get("role") or "").strip()

    payload: dict = {"company_name": company}
    if domain:           payload["domain"] = domain
    if location:         payload["location"] = location
    if industry:         payload["industry"] = industry
    if product_fit:      payload["product_fit"] = product_fit
    if inbound_role:     payload["inbound_role"] = inbound_role
    return payload

def xray_user_message(payload: dict) -> str:
    """Format the X-Ray payload as an instructional message for Claude."""
    company = payload.get("company_name", "the target company")
    lines = [
        f"Domain: {payload['domain']}" if payload.get("domain") else "",
        f"Location: {payload['location']}" if payload.get("location") else "",
        f"Industry / vertical: {payload['industry']}" if payload.get("industry") else "",
        f"Detected product fit: {payload['product_fit']}" if payload.get("product_fit") else "",
        f"Inbound contact role (title hint): {payload['inbound_role']}" if payload.get("inbound_role") else "",
    ]
    context = "\n".join(l for l in lines if l)

    return f"""Run X-Ray prospect discovery for the following company.

Target company: {company}
{context}

Instructions:
1. Use web_search now. Do NOT skip the tool call.
2. Run 3-4 efficient searches — favour a broad site:linkedin.com query that returns several people at once (aim for up to 15 people).
3. For each person found, verify name + company match in the snippet before including them.
4. Return ONLY the JSON array described in your system prompt. No preamble, no markdown fences.

Start searching immediately."""

RESEARCH_SYSTEM = "<withheld from the public build — see docs/agents/>"

def research_user_prompt(
    *,
    company: str,
    person: dict | None = None,
    lead: dict | None = None,
    notes: str = "",
) -> str:
    """
    The research request, carrying whatever the run already knows.

    The lead verdict is the point of running this inside a path. Lead scoring has
    already worked out *why* this company is warm — which pages they read, how
    strong the signal is, the product fit it inferred. Handing that over means the
    research starts from the real reason there is an opportunity, rather than
    rediscovering it from a company name. Run by hand there is no verdict, and the
    brief is correspondingly more generic.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("research_user_prompt is withheld from the public build.")

GTM_TARGETS_SYSTEM = """You propose the companies a salesperson should look at next.

You are working for Acme, which sells precision time synchronisation — PTP/IEEE-1588, GNSS, White Rabbit, grandmaster clocks, and timing-as-a-service — into finance, telecom, defence, broadcast, data centres and private 5G. Acme sells primarily into the UK, Europe and the Middle East; treat companies elsewhere as a weaker fit unless the request says otherwise.

# What you are producing

A **shortlist of candidates to check**, not a verified target list. You have no web access, so everything here comes from what you know, and what you know may be out of date — companies get acquired, renamed, and restructured. The person reading this will run each name through a research step before acting on it. Your job is to make that shortlist worth their time.

# What makes a good candidate

A company earns a place when what it does makes precision timing load-bearing:

1. **Structural fit** — they run a trading venue, a mobile network, a broadcast plant, a data centre, a private 5G deployment, or a defence/PNT programme.
2. **Named and specific** — a real operating company a salesperson could look up, not a market segment or a holding entity.
3. **Regionally plausible** — operating in the UK, Europe or the Middle East unless told otherwise.

Aim for eight to twelve candidates. Range matters more than certainty here: an obvious name and a less obvious one are both useful, and the check downstream is what separates them.

# Rules

- **Rank by confidence.** Put the companies you are most certain still exist, in this form, under this name, first.
- **Say what you are unsure about.** If a company may have been acquired or renamed, put that in `caveat`. An empty `caveat` is a claim of confidence — do not leave it empty out of laziness.
- **No invented specifics.** No headcount, revenue, site count, contract or deadline. `rationale` explains why timing matters to a company *of this kind*; it is not a claim about their current infrastructure.
- **No fabricated recency.** You cannot know what happened this quarter. Do not write "recently announced" or cite a date you are not sure of.
- **Do not return the seed company itself** when one is given — the request is for look-alikes.
- **Be short.** One sentence per field. British English.

# Output

Return ONLY a single JSON object, no preamble and no markdown fences:

{
  "companies": [
    {
      "name": "the operating company's name",
      "domain": "primary website domain if you are confident of it, else an empty string",
      "rationale": "one sentence — why precision timing is load-bearing for a company like this",
      "check": "one sentence — the specific thing worth verifying before approaching them",
      "caveat": "anything you are unsure of about the company itself, or an empty string"
    }
  ],
  "notes": "one sentence on how you scoped the list and what you deliberately left out"
}

Return `companies` as an empty array only if the request names a sector where precision timing genuinely has no role. A mainstream vertical always has candidates."""

def gtm_targets_user_prompt(analysis: dict, config: dict) -> str:
    """The target-company request, scoped by vertical and/or a seed company.

    `analysis` is `{vertical, seed_company, notes}` as built by the GTM route and
    the Owl tool. `notes` is where a steer lands, including the Signals watchlist
    digest — so a request the user has already shown interest in is weighted
    without the prompt needing to know Signals exists.
    """
    vertical = (analysis.get("vertical") or "").strip()
    seed = (analysis.get("seed_company") or "").strip()
    notes = (analysis.get("notes") or "").strip()

    known: list[str] = []
    if vertical:
        known.append(f"Vertical to target: {vertical}")
    if seed:
        known.append(f"Find companies that look like: {seed} (and exclude {seed} itself)")
    if notes:
        known.append("")
        known.append(f"Steer from the salesperson — weight towards this:\n{notes}")
    if config:
        known.append("")
        known.append(f"Configuration:\n{json.dumps(config, indent=2)}")

    context = "\n".join(known) or "(no scope given — say so rather than guessing)"

    return f"""Propose a shortlist of candidate companies worth checking.

{context}

Return ONLY the JSON object described in your system prompt."""

def owl_refine_gtm_targets_prompt(claude_output: dict, analysis: dict, config: dict) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("owl_refine_gtm_targets_prompt is withheld from the public build.")

CI_SHORTLIST_SYSTEM = "<withheld from the public build — see docs/agents/>"

CI_SYNTHESIS_SYSTEM = "<withheld from the public build — see docs/agents/>"

def ci_shortlist_prompt(
    *,
    vertical: str,
    company: str = "",
    index_text: str,
    want: int,
) -> str:
    """
    The retrieval request: the market, the account, and the whole index.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("ci_shortlist_prompt is withheld from the public build.")

def ci_synthesis_prompt(
    *,
    vertical: str,
    company: str = "",
    learnings: str,
    memory_topics: list[str] | None = None,
    notes: str = "",
) -> str:
    """
    The synthesis request, over the chosen learnings and the user's own history.

    `memory_topics` comes from `memory.topics_for_vertical` — what has already
    resonated across *this user's* accounts in this market. It is a different kind
    of evidence from the team's call learnings, so it is labelled as such rather
    than mixed in: one is what the market said, the other is what worked.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("ci_synthesis_prompt is withheld from the public build.")

COMPOSER_CHANNELS = ("email", "linkedin", "call")

COMPOSER_DRAFT_OVERLAY = "<withheld from the public build — see docs/agents/>"

COMPOSER_REFINE_OVERLAY = "<withheld from the public build — see docs/agents/>"

_COMPOSER_SHAPES = {
    "email": '  "email": {"subject": "", "body": ""}',
    "linkedin": '  "linkedin": {"connection_note": "", "follow_up": ""}',
    "call": '  "call": {"opener": "", "talking_points": ["", ""]}',
}

def _intel_block(intel: dict | None) -> str:
    """
    What the market has already told us, for the draft to write around.

    Canon's second grounding. Only the parts that inform a *first touch* are
    carried: what they will object to, what hurts, and how to open. The proof
    points and the recall trail belong to the outline, not to the email — a touch
    that cites four past calls is a different document.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("_intel_block is withheld from the public build.")

def composer_draft_prompt(
    *,
    brief: dict,
    channels: list[str],
    notes: str = "",
    intel: dict | None = None,
) -> str:
    """
    The draft request: the brief, the market's history, the mix, and the shape.

    `intel` is a Campaign Intelligence outline when the run has one. It is optional
    because composing without it is worse rather than impossible, and because a
    path that skips Campaign Intelligence must still walk — so with `intel` absent
    this prompt is byte-identical to what it was before Campaign Intelligence
    existed.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("composer_draft_prompt is withheld from the public build.")

def composer_refine_prompt(draft: dict) -> str:
    """
    The refine request, carrying the draft as JSON.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("composer_refine_prompt is withheld from the public build.")

CALL_ANALYSIS_ROLE = "<withheld from the public build — see docs/agents/>"

def call_identity_tail(first_name: str, role: str = "") -> str:
    """
    The per-user tail that sits after the cache breakpoint.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("call_identity_tail is withheld from the public build.")

def call_analysis_prompt(*, transcript: str, name: str) -> str:
    """
    The analysis request. Unchanged from the module this moved out of.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("call_analysis_prompt is withheld from the public build.")

def product_fit_prompt(*, analysis: dict, product_name: str = "") -> str:
    """
    The product-fit request, built from the stored reading rather than the call.

    Distilled from the analysis on purpose: the summary, signals, objections,
    concepts and talking points are what a fit judgement needs, and re-sending the
    transcript would pay for it twice.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("product_fit_prompt is withheld from the public build.")

RECAP_DRAFT_OVERLAY = "<withheld from the public build — see docs/agents/>"

RECAP_REFINE_OVERLAY = "<withheld from the public build — see docs/agents/>"

def recap_draft_prompt(*, analysis: dict, title: str = "", notes: str = "") -> str:
    """
    The draft request, built from the call's reading.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("recap_draft_prompt is withheld from the public build.")

def recap_refine_prompt(draft: dict) -> str:
    """
    The refine request, carrying the draft as JSON.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("recap_refine_prompt is withheld from the public build.")

SIGNALS_SYSTEM = "<withheld from the public build — see docs/agents/>"

def signals_prompt(*, company: str, known: list[str] | None = None) -> str:
    """
    The monitoring request for one company.

    `known` is a short list of headlines already reported. It is passed so the model
    does not spend its searches re-finding them — the agent's fingerprint check is
    what actually guarantees they are not reported twice, and this is only an
    efficiency. Kept short: the point is a hint, not a second filter.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("signals_prompt is withheld from the public build.")

