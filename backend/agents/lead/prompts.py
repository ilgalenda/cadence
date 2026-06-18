from __future__ import annotations
"""Pass-1 (Claude generation) and pass-2 (Owl refinement) prompts."""
import json


# ---------------------------------------------------------------------------
# Pass 1 — Claude (raw generation, no Timebeat persona)
# ---------------------------------------------------------------------------

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
    return f"""Analyse this inbound lead for a B2B sales team selling Timebeat,
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
  "product_fit": "best-guess Timebeat product line",
  "suggested_campaign_type": "email" | "linkedin",
  "suggested_campaign_reasoning": "one sentence",
  "source": "where this lead likely came from"
}}

If a value is unknown, use an empty string. Be specific, not generic."""


def _word_limit_for(strength: str | None) -> int:
    # KB Section 4: warm/hot=100 words, cold=80 words.
    return 80 if (strength or "").strip().lower() == "cold" else 100


def claude_sequence_prompt(analysis: dict, config: dict, recipient: dict | None = None) -> str:
    n = int(config.get("touches", 4))
    strength = (analysis or {}).get("signal_strength", "")
    word_limit = _word_limit_for(strength)
    recipient_block = ""
    if recipient:
        rname = recipient.get("name") or "(unknown name)"
        rrole = recipient.get("role") or "(role not specified)"
        rli = recipient.get("linkedin_url") or "(no LinkedIn URL provided)"
        recipient_block = f"""
This sequence is for ONE specific recipient — personalise every touch to them.
Reference their name and role naturally where it fits. If a LinkedIn URL is
provided, use the URL itself as a hint to their seniority and focus, but do
NOT pretend you have visited it.

Recipient:
  name: {rname}
  role: {rrole}
  linkedin_url: {rli}
"""

    return f"""Write a {n}-touch outbound email sequence for Timebeat that reads
like one sharp salesperson wrote it to one specific person — not a template.

Signal strength: {strength or 'unspecified'}. Hard word limit per email: {word_limit}.
{recipient_block}
Lead analysis (account-level context — same for all recipients):
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

How to make it sound human, not automated:
- Open each email differently. Vary sentence length and rhythm. Contractions are fine.
- Say something only Timebeat would say to *this* person — a specific protocol,
  product, regulation, or pain that fits their world. Generic = delete it.
- One idea per email. Earn the next email; don't cram the whole pitch into touch 1.
- Write the way you'd actually email a busy engineer or buyer: direct, curious,
  a little informal, never gushing or salesy.

Guardrails (hard):
- Each email strictly under {word_limit} words.
- Banned filler: "I hope this finds you well", "Just following up", "Circling
  back", "Touching base", "I wanted to reach out", "quick question".
- Subject lines: specific and concrete, lowercase is fine, no clickbait, no emoji.
- The sequence should build naturally — early touches earn attention, later ones
  add a new angle or gently make the ask. Don't follow a rigid script; let the
  lead's situation shape the arc. If materials are provided, use them where they
  genuinely help, not everywhere.

Return ONLY a JSON object:
{{
  "touches": [
    {{
      "touch": 1,
      "subject": "string",
      "body": "string (under 100 words)",
      "angle": "Acknowledge signal" | "Value add" | "Soft ask" | "New angle" | "Break-up",
      "suggested_day": "e.g. Day 1, Day 4, Day 8",
      "send_time": "e.g. Tuesday 9am"
    }}
  ]
}}"""


def claude_touch_regen_prompt(analysis: dict, config: dict, sequence: list[dict], n: int, recipient: dict | None = None) -> str:
    word_limit = _word_limit_for((analysis or {}).get("signal_strength"))
    recipient_block = ""
    if recipient:
        recipient_block = f"\nRecipient: {recipient.get('name','')} — {recipient.get('role','')} ({recipient.get('linkedin_url','no LinkedIn')})\n"
    return f"""Regenerate ONLY touch #{n} of this email sequence with a fresh angle
while keeping it consistent with the rest of the sequence.
{recipient_block}
Lead analysis:
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Existing sequence:
{json.dumps(sequence, indent=2)}

Same rules as the original generation: strictly under {word_limit} words, no filler ("I hope this finds you well", "Just following up", "Circling back"), specific subject.

Return ONLY a JSON object for the single replacement touch:
{{
  "touch": {n},
  "subject": "string",
  "body": "string",
  "angle": "string",
  "suggested_day": "string",
  "send_time": "string"
}}"""


def claude_boolean_prompt(analysis: dict, config: dict) -> str:
    return f"""Generate a complete LinkedIn outreach package for Dripify: a boolean
search string (primary + broader alternative), a connection-request message, and
a 3-step post-connection drip sequence.

Lead analysis:
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Boolean rules:
- Use OR for role variants, AND for must-haves, NOT for exclusions.
- Quote multi-word terms.
- Format for LinkedIn Sales Navigator.

Connection message rules (KB Section 4):
- STRICT max 300 characters (mobile-friendly).
- Lead with the prospect's world, not Timebeat's product.
- No pitch in the connection request.
- Human, not templated.
- Creates curiosity without over-explaining.

Drip sequence rules (KB Section 5 — Dripify drip steps):
- Exactly 3 follow-up messages, sent AFTER the prospect accepts the connection.
- Step 1: warm thank-you / context, 2 days after accept.
- Step 2: value-add (insight / use case / resource), 4 days later.
- Step 3: soft ask (one question or one link), 4 days later.
- Each message under 600 characters, no filler phrases, plain text.

Return ONLY a JSON object:
{{
  "primary": "the focused boolean string",
  "alternative": "a broader variant for larger pools",
  "filters": [
    {{ "name": "Seniority level", "values": ["..."] }},
    {{ "name": "Company headcount", "values": ["..."] }},
    {{ "name": "Geography", "values": ["..."] }},
    {{ "name": "Industry", "values": ["..."] }}
  ],
  "audience_note": "one-sentence estimate of audience size and quality",
  "connection_message": "string under 300 characters",
  "drip_sequence": [
    {{ "step": 1, "delay_days": 2, "body": "..." }},
    {{ "step": 2, "delay_days": 4, "body": "..." }},
    {{ "step": 3, "delay_days": 4, "body": "..." }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Pass 2 — Owl (Timebeat-grounded refinement)
# ---------------------------------------------------------------------------

def owl_refine_signal_prompt(claude_output: dict, lead_blob: str) -> str:
    return f"""You are refining a lead analysis produced by another model.
Re-check product_fit against the actual Timebeat product lines in your
knowledge base. Tighten reasoning. Flag anything unsupported.

Original lead input:
{lead_blob}

Pass-1 output:
{json.dumps(claude_output, indent=2)}

Return ONLY the refined JSON in the same shape as the pass-1 output."""


def owl_refine_sequence_prompt(claude_output: dict, analysis: dict, config: dict) -> str:
    word_limit = _word_limit_for((analysis or {}).get("signal_strength"))
    return f"""You are refining an email sequence produced by another model so it
sounds like a real, knowledgeable Timebeat salesperson wrote it — human and
interesting, never automated or templated.

Do this:
- Rewrite anything that reads like AI or a mail-merge. Vary the openings; no two
  emails should start the same way. Use natural rhythm and the occasional
  contraction. Cut throat-clearing — get to the point.
- Replace generic claims with specific, real Timebeat product / protocol
  references from the knowledge base (never invent). One concrete idea per email.
- Tighten subject lines to something a busy person would actually open.
- Keep the facts from the lead (names, company, role) intact.

Guardrails (hard): under {word_limit} words per email; no filler ("I hope this
finds you well", "Just following up", "Circling back", "Touching base", "I wanted
to reach out", "quick question").

Lead analysis:
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Pass-1 output:
{json.dumps(claude_output, indent=2)}

Return ONLY the refined JSON in the exact same shape: {{ "touches": [...] }}."""


def owl_refine_touch_prompt(claude_output: dict, analysis: dict, config: dict, sequence: list[dict], n: int) -> str:
    word_limit = _word_limit_for((analysis or {}).get("signal_strength"))
    return f"""You are refining a single replacement touch (#{n}) produced by
another model. Rewrite in the Timebeat voice. Keep it strictly under {word_limit}
words and consistent with the rest of the sequence.

Sequence so far:
{json.dumps(sequence, indent=2)}

Pass-1 replacement touch:
{json.dumps(claude_output, indent=2)}

Return ONLY the refined JSON for the single touch in the same shape."""


def owl_refine_boolean_prompt(claude_output: dict, analysis: dict, config: dict) -> str:
    return f"""You are refining a LinkedIn outreach package produced by another
model. The package contains a boolean search, a connection-request message, and
a 3-step Dripify drip sequence.

Refinement rules:
- Boolean: add Timebeat-vertical-aware role variants (PTP, timing, network sync,
  GNSS, latency-sensitive industries). Tune keyword include/exclude using your
  Timebeat knowledge.
- Connection message: enforce ≤300 characters. No pitch. Lead with the
  prospect's world, not Timebeat's product. Rewrite in the Timebeat voice.
- Drip sequence: rewrite each body in the Timebeat voice, ensure each follow-up
  has one clear purpose (warm thank-you / value-add / soft ask), no filler,
  each under 600 characters.

Lead analysis:
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Pass-1 output:
{json.dumps(claude_output, indent=2)}

Return ONLY the refined JSON in the exact same shape, including
connection_message and drip_sequence."""

# ---------------------------------------------------------------------------
# ABM (Multi-Channel Account Push) — KB Section 2.3 Archetype 3 + Section 6
# ---------------------------------------------------------------------------

def claude_abm_identification_prompt(analysis: dict, config: dict) -> str:
    """Used when only an organisation-level signal exists. Returns a LinkedIn
    boolean to find 2-3 personas inside the account, plus a Lusha enrichment
    checklist. KB Section 6 — contact identification.
    """
    return f"""An ABM campaign needs to identify named contacts inside a target
organisation before any outreach can begin. Generate the identification plan.

Lead analysis (account-level):
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Persona priority (KB Section 1.5):
1. Technical evaluator first — Network Engineer, IT Infrastructure Manager,
   Systems Administrator, Timing Engineer.
2. Then economic buyer — CTO, CIO, Director of IT/Digital, Head of Infrastructure.
3. Procurement only when the deal nears closing.

Boolean rules:
- Scope strictly to the target organisation (use a Company filter equivalent).
- Use OR for role variants, AND for must-haves, NOT for exclusions.
- Quote multi-word terms.

Return ONLY a JSON object:
{{
  "boolean_primary": "boolean string scoped to the target org, technical-evaluator focus",
  "boolean_alternative": "broader boolean covering economic buyers as a fallback",
  "personas": [
    {{ "priority": 1, "title": "Network Engineer / IT Infrastructure Manager", "why": "one sentence" }},
    {{ "priority": 2, "title": "CIO / Director of IT", "why": "one sentence" }}
  ],
  "lusha_checklist": [
    "Run boolean above in LinkedIn Sales Navigator scoped to the company.",
    "Shortlist 2–3 names per persona priority.",
    "Enrich with Lusha for verified work emails.",
    "Add enriched contacts to the campaign before generating the 4-week sequence."
  ],
  "notes": "one-sentence guidance on what 'good' looks like for this account"
}}"""


def claude_abm_sequence_prompt(analysis: dict, config: dict, contacts: list[dict]) -> str:
    """4-week LinkedIn + email matrix per KB Section 6."""
    word_limit = _word_limit_for((analysis or {}).get("signal_strength"))
    contacts_block = json.dumps(contacts or [], indent=2)
    return f"""Build a 4-week ABM campaign across LinkedIn (Dripify) and email,
following KB Section 6 exactly. Coordinate the two tracks but do NOT make them
identical — different angle on the same week.

Lead analysis (account-level):
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Identified contacts (one cell of the matrix per contact per week per channel):
{contacts_block}

Week-by-week structure:
  Week 1 — LinkedIn: connection request (≤300 chars, no pitch, lead with their world).
           Email: none yet.
  Week 2 — LinkedIn: post-accept follow-up (warm context, ≤600 chars).
           Email: first email — short intro, acknowledge their org's relevance.
  Week 3 — LinkedIn: value-add (insight, use case, resource).
           Email: value-add email — different angle from the LinkedIn message.
  Week 4 — LinkedIn: soft ask (one question or call invite).
           Email: soft ask email — different phrasing from LinkedIn.

Rules:
- Email word limit: strictly under {word_limit}.
- LinkedIn message length: ≤300 chars (Week 1), ≤600 chars (Weeks 2–4).
- No filler phrases.
- Each week's two messages should feel coordinated but not duplicated.
- Personalise per contact (name, role) where contacts are provided.

Return ONLY a JSON object:
{{
  "matrix": [
    {{
      "week": 1,
      "linkedin": [
        {{ "contact_id": "string or empty", "contact_name": "string", "body": "≤300 chars" }}
      ],
      "email": []
    }},
    {{
      "week": 2,
      "linkedin": [
        {{ "contact_id": "...", "contact_name": "...", "body": "≤600 chars" }}
      ],
      "email": [
        {{ "contact_id": "...", "contact_name": "...", "subject": "string", "body": "string under {word_limit} words" }}
      ]
    }},
    {{ "week": 3, "linkedin": [...], "email": [...] }},
    {{ "week": 4, "linkedin": [...], "email": [...] }}
  ],
  "coordination_note": "one sentence on how the two tracks differ in angle"
}}"""


def owl_refine_abm_identification_prompt(claude_output: dict, analysis: dict, config: dict) -> str:
    return f"""You are refining an ABM identification plan produced by another
model. Tighten the boolean to actually scope inside the target organisation.
Confirm persona priority follows KB Section 1.5 (technical evaluator first).
Tighten Lusha checklist into concrete actions.

Lead analysis:
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Pass-1 output:
{json.dumps(claude_output, indent=2)}

Return ONLY the refined JSON in the same shape."""


def owl_refine_abm_sequence_prompt(claude_output: dict, analysis: dict, config: dict, contacts: list[dict]) -> str:
    word_limit = _word_limit_for((analysis or {}).get("signal_strength"))
    return f"""You are refining a 4-week ABM matrix produced by another model.
Rewrite every cell in the Timebeat voice using the knowledge base. Replace
generic claims with specific Timebeat product / protocol references.

Hard rules:
- Email bodies strictly under {word_limit} words.
- LinkedIn Week-1 messages strictly ≤300 chars.
- LinkedIn Weeks 2–4 strictly ≤600 chars.
- LinkedIn and email on the same week must NOT be near-duplicates — different
  angles on the same theme.
- No filler phrases.

Lead analysis:
{json.dumps(analysis, indent=2)}

Configuration:
{json.dumps(config, indent=2)}

Identified contacts:
{json.dumps(contacts or [], indent=2)}

Pass-1 output:
{json.dumps(claude_output, indent=2)}

Return ONLY the refined JSON in the exact same shape: {{ "matrix": [...], "coordination_note": "..." }}."""


# ---------------------------------------------------------------------------
# X-Ray sub-agent — LinkedIn / public-web prospect discovery via web_search
# ---------------------------------------------------------------------------

XRAY_SYSTEM_PROMPT = """You are an X-Ray research agent operating inside Timebeat's sales cadence platform. Timebeat sells precision time synchronisation infrastructure (PTP / IEEE 1588, GNSS receivers, time-as-a-service) to organisations with strict timing or regulatory clock-sync requirements.

# Timebeat ICP (use this as your persona reference)

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
- linkedin_url (or other public profile URL if no LinkedIn)
- confidence: high / medium / low
  - high: name, title, company all confirmed in snippet
  - medium: name and company match, title is approximate
  - low: partial match or ambiguous snippet
- recommended_path:
  - "linkedin_direct": LinkedIn profile confirmed — push to Dripify outreach
  - "email_enrichment": profile found but email needed before outreach
  - "campaign_context": useful for personalisation but not a direct target
- match_reason: 1-2 sentences explaining WHY this person is a strong outreach target for Timebeat. Ground the argument in the knowledge base — reference Timebeat ICP signals, regulatory drivers (e.g. MiFID II clock-sync, FINRA, MAS), product fit, role-specific pain points, or public signals from the snippet. Do NOT write generic LinkedIn boilerplate. Every name needs a concrete, KB-grounded argument.
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
    "linkedin_url": "",
    "confidence": "high | medium | low",
    "recommended_path": "linkedin_direct | email_enrichment | campaign_context",
    "match_reason": "",
    "source_query": ""
  }
]

If no results meet the quality bar, return [].
"""


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
            "\n\n# Timebeat customer personas (AUTHORITATIVE — overrides the generic ICP above)\n\n"
            "The following personas are derived from Timebeat's actual customers. "
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

    industry = (
        structured.get("industry")
        or structured.get("vertical")
        or signal_final.get("signal_type")
        or ""
    ).strip()
    product_fit = (signal_final.get("product_fit") or "").strip()
    signal_strength = (signal_final.get("signal_strength") or "").strip()
    inbound_role = (signal_final.get("role") or "").strip()

    payload: dict = {"company_name": company}
    if domain:           payload["domain"] = domain
    if location:         payload["location"] = location
    if industry:         payload["industry"] = industry
    if product_fit:      payload["product_fit"] = product_fit
    if signal_strength:  payload["signal_strength"] = signal_strength
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
        f"Signal strength: {payload['signal_strength']}" if payload.get("signal_strength") else "",
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


