"""Prompt library — public showcase build.

Cadence keeps every prompt in one module so they can be reviewed, diffed and
version-controlled as a body of work rather than scattered through agent code.

This is the redacted build of that module. The prompts for the three exemplar
agents are present in full; the rest keep their signatures and docstrings and
lose their bodies. Regenerate with tools/redact-prompts.py — do not hand-edit.
"""


from __future__ import annotations

import json

DETECTION_SYSTEM_PROMPT = "<withheld from the public build — see docs/agents/>"

SIGNAL_TYPE_INSTRUCTIONS = {
    "competitor_engagement": """
# Signal type: Competitor Engagement

Search for people who have publicly engaged with competitors (LinkedIn posts, articles, conference mentions, podcast appearances, job postings referencing competitor tools).

Query strategies:
1. `site:linkedin.com/posts "[competitor_name]"` — find public posts mentioning the competitor
2. `"[competitor_name]" LinkedIn comment OR discussion` — find public discussions
3. `"[competitor_name]" "[title]" speaker OR conference` — conference mentions signal active buyers
4. `"[competitor_name]" RFP OR evaluation OR review` — procurement signals
5. `"[competitor_name]" "[industry]" integration OR deployment` — implementation discussions

Focus on: people who are clearly evaluating or actively using timing/sync competitors. Their engagement = active market participation.
""",

    "influencer_engagement": """
# Signal type: Influencer Engagement

Search for people engaging with timing/sync influencer content, IEEE 1588 working group discussions, PTP-related conference talks, or relevant hashtag communities.

Query strategies:
1. `site:linkedin.com "[influencer_name]" commented` — public comments on influencer posts
2. `"#PTP" OR "#IEEE1588" OR "#timesync" LinkedIn` — hashtag discussions
3. `"[influencer_name]" "[industry]" interview OR panel` — conference co-appearances
4. `IEEE 1588 working group "[company_type]"` — working group participation signals active buyers
5. `"timing synchronisation" OR "time sync" "[industry]" conference 2024 OR 2025` — recent conference discussions
""",

    "job_change": """
# Signal type: Recently Changed Roles

Search for people who recently started a new role relevant to timing, network infrastructure, or trading technology at ICP companies. New roles = new mandate, potential new budget.

Query strategies:
1. `site:linkedin.com "[title]" "started" OR "joined" "[industry]"` — LinkedIn new role announcements
2. `"[company_type]" "[title]" appointed OR hired 2024 OR 2025` — press announcements
3. `"[title]" "[industry]" new appointment 2024 OR 2025` — industry press
4. `"[company]" leadership team infrastructure OR technology` — updated leadership pages
5. `"[title]" "[company_type]" LinkedIn 2025` — recent profile updates

Focus on: VP/Head/Director level appointments in infrastructure, network, trading technology, compliance tech at financial institutions, telecoms, data centres.
""",

    "funding": """
# Signal type: Recently Funded

Search for companies in Acme's target verticals that recently announced funding. Funded companies = growth mode, new infrastructure spending, open budget.

Query strategies:
1. `"[industry]" funding 2024 OR 2025 site:techcrunch.com OR site:crunchbase.com` — funding news
2. `"[industry]" "Series A" OR "Series B" OR "seed" 2025 infrastructure OR platform` — stage-specific news
3. `"[company_name]" raised funding infrastructure OR timing OR network` — company-specific
4. `fintech OR HFT OR telecoms funding infrastructure technology 2025` — broad sector funding
5. `"[company]" "CTO" OR "VP Technology" site:linkedin.com` — find decision-makers at funded co

After finding a recently funded company, find the relevant decision-makers (CTO, VP Infrastructure, Head of Network) at that company.
""",

    "top_icp": """
# Signal type: Top 5% ICP Activity

Search for highly active professionals in Acme's target verticals who are publicly visible — conference speakers, podcast guests, authors of technical articles, working group participants.

Active professionals = higher responsiveness and more likely to be current buyers or influencers.

Query strategies:
1. `"[title]" "[industry]" conference speaker 2024 OR 2025` — recent conference speakers
2. `"[title]" "[industry]" podcast interview 2024 OR 2025` — recent podcast guests
3. `"[title]" "[industry]" article OR blog OR whitepaper` — published authors
4. `IEEE 1588 OR PTP OR GNSS working group participant "[industry]"` — working group members
5. `"[title]" "[industry]" LinkedIn active posts 2025` — recent LinkedIn activity
""",

    "company_engagement": """
# Signal type: Engaged with Acme

Search for people who have publicly mentioned Acme, Open Timecard, Clock Quorum, or Acme's products in posts, articles, conference talks, or discussions.

Query strategies:
1. `"Acme" site:linkedin.com` — LinkedIn mentions
2. `"Open Timecard" OR "Clock Quorum" OR "Acme" discussion OR review` — public mentions
3. `"Acme" conference OR event OR keynote` — event mentions
4. `"Acme" customer OR deployment OR case study` — implementation references
5. `"Acme" GitHub OR forum OR community` — technical community engagement

These people already know Acme exists — outreach converts faster.
""",
}

def detection_user_message(signal_type: str, icp_config: dict) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("detection_user_message is withheld from the public build.")

COMPOSE_ROLE = "<withheld from the public build — see docs/agents/>"

def compose_user_message(signal: dict, enriched: dict | None = None) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("compose_user_message is withheld from the public build.")

FOLLOWUP_USER_MESSAGE_TEMPLATE = "<withheld from the public build — see docs/agents/>"

def followup_user_message(signal: dict, reply_text: str) -> str:
    """
    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("followup_user_message is withheld from the public build.")

