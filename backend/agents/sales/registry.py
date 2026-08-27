"""Where the sales agents announce themselves to Owl.

Importing this module registers every migrated agent. It is imported once, by
`agents.sales.routes`, so the roster is a consequence of mounting the sales
surface rather than something a caller has to remember.

Each entry is the *only* declaration of that agent as a tool: schema and runner
together, so Owl can never be offered a tool that nothing can execute.
"""
from __future__ import annotations

from agents.sales import tools
from agents.sales.call_analysis import agent as call_analysis
from agents.sales.campaign_intelligence import agent as campaign_intelligence
from agents.sales.campaign_selection import agent as campaign_selection
from agents.sales.composer import agent as composer
from agents.sales.gtm import agent as gtm
from agents.sales.knowledge_capture import agent as knowledge_capture
from agents.sales.recap import agent as recap
from agents.sales.research import agent as research
from agents.sales.signals import agent as signals
from agents.sales.scoring import agent as scoring
from agents.sales.xray import agent as xray


def register_all() -> None:
    """Register the agents that have migrated. Idempotent across imports."""
    if tools.names():
        return

    tools.register(tools.SalesTool(
        name="score_lead",
        description=(
            "Score an inbound or website lead from its behavioural signal — how hot it is, "
            "graded, with the behaviour that drove the score. Deterministic: the same "
            "behaviour always gives the same grade. Use when the user pastes visit data, a "
            "form submission, or describes what a visitor did."
        ),
        input_schema=scoring.TOOL_SCHEMA,
        run=scoring.run_as_tool,
        writes=False,
    ))

    tools.register(tools.SalesTool(
        name="find_target_companies",
        description=(
            "Propose companies worth approaching for outbound — by vertical or ICP, or as "
            "look-alikes of a seed company. Returns proposals for the user to select from; "
            "it does not start any outreach. Use when the user asks who to target."
        ),
        input_schema=gtm.TOOL_SCHEMA,
        run=gtm.run_as_tool,
        writes=False,
    ))

    tools.register(tools.SalesTool(
        name="xray",
        description=(
            "Find the named people worth approaching at a company — everyone matching the "
            "ICP, with the argument for each one. Searches public profiles. To sweep for "
            "people showing a buying signal across companies instead, use the signals tool. "
            "Does NOT enrich: emails and phone numbers are revealed later, on the shortlist "
            "the user selects, because that spends credit."
        ),
        input_schema=xray.TOOL_SCHEMA,
        run=xray.run_as_tool,
        writes=False,
    ))

    tools.register(tools.SalesTool(
        name="research_account",
        description=(
            "Research a company, and optionally one decision-maker at it, into a single "
            "brief: what they do, why timing matters to them now, the product angle, and "
            "how to approach the person. Searches the web and cites sources. Use before "
            "writing outreach, or whenever the user asks what we know about an account."
        ),
        input_schema=research.TOOL_SCHEMA,
        run=research.run_as_tool,
        # It records the account in the user's memory, which is a write — a caller
        # deciding what is safe to run unattended needs to know that.
        writes=True,
    ))

    tools.register(tools.SalesTool(
        name="recall_market",
        description=(
            "Recall what past Acme calls in a market taught us: the objections that "
            "come up, the pain points, what has landed before, and how to open. Reads the "
            "team's analysed calls — it does NOT search the web, so use research_account "
            "for anything about a specific company's current situation. Use before "
            "choosing a campaign or writing outreach, or when the user asks what a "
            "market usually says."
        ),
        input_schema=campaign_intelligence.TOOL_SCHEMA,
        run=campaign_intelligence.run_as_tool,
        # Reads the vault and the user's memory; writes nothing, files nothing.
        writes=False,
    ))

    tools.register(tools.SalesTool(
        name="select_campaign",
        description=(
            "Work out the shape of the campaign for a lead — which archetype (warm inbound "
            "re-engagement or ABM account push), the channel mix, how many touches and the "
            "sequence structure. Deterministic: the same lead always gives the same plan. "
            "It computes the eligible plan; the user chooses. Use before writing outreach, "
            "or when the user asks how to run a campaign."
        ),
        input_schema=campaign_selection.TOOL_SCHEMA,
        run=campaign_selection.run_as_tool,
        # Pure computation over its arguments — no store, no queue, no spend.
        writes=False,
    ))

    tools.register(tools.SalesTool(
        name="compose_outreach",
        description=(
            "Write first-touch outreach — email, LinkedIn, or a call opener — for a company "
            "and person, in Owl's voice and the user's own writing style. Files the result "
            "for the user to review; it never sends anything. Research the account first "
            "for materially better touches."
        ),
        input_schema=composer.TOOL_SCHEMA,
        run=composer.run_as_tool,
        # Files a review item, which is a write the caller should know about.
        writes=True,
    ))

    tools.register(tools.SalesTool(
        name="check_signals",
        description=(
            "Report what is new at the accounts on the watchlist — funding, contracts, "
            "build-outs, timing work, compliance deadlines. Every finding carries a "
            "source. Pass a company to check one now whether or not it is watched. Use "
            "when the user asks what has changed at their accounts, or before targeting."
        ),
        input_schema=signals.TOOL_SCHEMA,
        run=signals.run_as_tool,
        # Records what was checked and what was found, so a later sweep does not
        # report the same event again.
        writes=True,
    ))

    # ── The back half: after the conversation has happened ──────────────────

    tools.register(tools.SalesTool(
        name="analyse_call",
        description=(
            "Read a pasted call or meeting transcript from a sales perspective: a summary, "
            "the buying signals, the objections raised, talking points, and the Acme "
            "concepts mentioned. Files the call to the library. Use when the user pastes a "
            "transcript or asks what a call surfaced."
        ),
        input_schema=call_analysis.TOOL_SCHEMA,
        run=call_analysis.run_as_tool,
        # It files the call to the library, which is a write worth declaring.
        writes=True,
    ))

    tools.register(tools.SalesTool(
        name="draft_recap",
        description=(
            "Write the follow-up email for a call that has already been analysed — what was "
            "covered and the next steps, in writing, for the client. Files it for review; it "
            "never sends. Needs the call's id, so analyse the call first."
        ),
        input_schema=recap.TOOL_SCHEMA,
        run=recap.run_as_tool,
        # Files a review item.
        writes=True,
    ))

    tools.register(tools.SalesTool(
        name="capture_learnings",
        description=(
            "Stage what an analysed call taught the company into the shared vault — the "
            "learnings and any genuinely new glossary terms. Normally runs automatically as "
            "part of an analysis; use this to repeat it for a specific call. Terms that "
            "already exist are skipped."
        ),
        input_schema=knowledge_capture.TOOL_SCHEMA,
        run=knowledge_capture.run_as_tool,
        # Writes to the shared vault — the most consequential write in the roster.
        writes=True,
    ))
