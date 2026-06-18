from __future__ import annotations
"""Conversational campaign builder.

Owl chats with the user to shape an outreach campaign for a specific lead, then
calls the existing generation pipeline via tool use. Each tool result is
persisted onto the campaign, so the frontend simply re-hydrates the campaign to
render the produced artifact (sequence / boolean / ABM matrix).

Non-streaming agentic loop: simpler and more reliable than streaming tool use,
and generation is a multi-second pipeline call anyway. Owl's job is to decide
*what* to build (type, tone, touches) in a human, consultative voice; the proven
pipeline does the actual writing.
"""
import json
import os
import uuid

import anthropic

from agents.lead import pipeline, storage
from agents.lead.knowledge import owl_system_blocks
from agents.shared.vault import log_cache_usage

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ROUNDS = 4

BUILDER_INSTRUCTIONS = """

# Your job right now: build an outreach campaign with this person

You are helping a Timebeat salesperson turn the lead below into a campaign. Talk
like a sharp colleague, not a wizard: short, human replies, British English.

How to run the conversation:
- Open by reading the signal and the behavioural score, and *recommend* a
  campaign type with one line of reasoning (email sequence, LinkedIn/Dripify, or
  multi-channel ABM). Hot/clear-intent leads → fewer, sharper touches; cold or
  account-only signals → LinkedIn or ABM.
- Ask at most one or two quick questions only if you genuinely need them (tone,
  focus, number of touches). Don't interrogate. If the user says "you decide" or
  gives you enough, just proceed.
- When you and the user agree on the approach, CALL THE MATCHING TOOL to generate
  it. Don't describe the emails yourself — the tool writes them.
- After a tool runs, give a one or two sentence summary of what you built and
  invite a tweak (regenerate a touch, change tone, try a different channel).
- The user can always change direction; regenerate by calling the tool again
  with new settings.

Defaults if the user doesn't specify: tone=Consultative, focus=Sales, touches by
signal strength (Hot 3, Warm 4, Cold 5)."""

TOOLS = [
    {
        "name": "generate_email_sequence",
        "description": "Generate a personalised multi-touch email sequence for the lead's recipients. Use for warm/hot leads or when the user wants email outreach.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tone": {"type": "string", "enum": ["Consultative", "Technical", "Direct"]},
                "focus": {"type": "string", "enum": ["Sales", "Technical", "Thought leadership"]},
                "touches": {"type": "integer", "minimum": 3, "maximum": 5},
                "materials": {"type": "string", "description": "Optional materials to reference."},
                "case_study": {"type": "string", "description": "Optional case study name/URL."},
                "cadence": {"type": "string", "description": "e.g. 'Every 2 days'."},
            },
            "required": ["tone", "focus", "touches"],
        },
    },
    {
        "name": "generate_linkedin_boolean",
        "description": "Generate a LinkedIn Sales Navigator boolean search + Dripify connection message + drip sequence. Use when LinkedIn outreach fits better than email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "industry": {"type": "string"},
                "roles": {"type": "array", "items": {"type": "string"}},
                "company_size": {"type": "array", "items": {"type": "string"}},
                "geography": {"type": "string"},
                "keywords_include": {"type": "string"},
                "keywords_exclude": {"type": "string"},
            },
        },
    },
    {
        "name": "generate_abm_sequence",
        "description": "Generate a 4-week multi-channel ABM matrix (LinkedIn + email) across the campaign's contacts. Use for account-level pushes with multiple personas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string"},
                "geography": {"type": "string"},
                "why_now": {"type": "string", "description": "Trigger / reason to engage now."},
            },
        },
    },
]


def _lead_context_block(campaign: dict) -> str:
    a = campaign.get("signal_analysis") or {}
    recipients = campaign.get("recipients") or campaign.get("contacts") or []
    lines = [
        "# This lead",
        f"Company: {a.get('company', '')}",
        f"Contact: {a.get('contact_name', '') or '(unknown — may need prospecting)'}",
        f"Role: {a.get('role', '')}",
        f"Signal: {a.get('signal_strength', '?')} — {a.get('signal_type', '')}",
        f"Product fit: {a.get('product_fit', '')}",
    ]
    if a.get("lead_score") is not None:
        lines.append(f"Behavioural score: {a.get('lead_score')} (grade {a.get('lead_grade', '?')})")
        if a.get("score_signals"):
            lines.append("Score signals: " + "; ".join(a["score_signals"]))
    if recipients:
        who = ", ".join(f"{r.get('name', '?')} ({r.get('role', '')})" for r in recipients[:8])
        lines.append(f"Recipients on file ({len(recipients)}): {who}")
    else:
        lines.append("Recipients on file: none yet — email needs at least the named contact; ABM/LinkedIn can target by role.")
    return "\n".join(lines)


def _builder_system(username: str, campaign: dict) -> list[dict]:
    blocks = list(owl_system_blocks(username))  # cached persona + vault
    blocks.append({"type": "text", "text": BUILDER_INSTRUCTIONS + "\n\n" + _lead_context_block(campaign)})
    return blocks


def _ensure_recipients(campaign: dict) -> list[dict]:
    recipients = campaign.get("recipients") or []
    if recipients:
        return recipients
    a = campaign.get("signal_analysis") or {}
    return [{
        "id": uuid.uuid4().hex[:12],
        "name": a.get("contact_name", ""),
        "role": a.get("role", ""),
        "linkedin_url": "",
    }]


def _execute_tool(name: str, args: dict, campaign: dict, username: str, sandbox: bool) -> tuple[str, str | None]:
    """Run a generation tool, persist to the campaign, return (summary, artifact_type)."""
    cid = campaign["id"]
    analysis = campaign.get("signal_analysis") or {}

    if name == "generate_email_sequence":
        config = {
            "tone": args.get("tone", "Consultative"),
            "focus": args.get("focus", "Sales"),
            "touches": int(args.get("touches", 4)),
            "materials": args.get("materials", ""),
            "case_study": args.get("case_study"),
            "cadence": args.get("cadence", "Every 2 days"),
        }
        recipients = _ensure_recipients(campaign)
        result = pipeline.generate_sequences(username, analysis, config, recipients)
        out_recipients = result["recipients"]
        storage.patch_campaign(cid, {
            "email_config": config,
            "recipients": out_recipients,
            "email_sequence": (out_recipients[0]["sequence"] if out_recipients else []),
            "campaign_type": "email",
            "current_step": 4,
            "status": "ready",
        }, username=username, sandbox=sandbox)
        total = sum(len(r["sequence"]) for r in out_recipients)
        return (f"Generated a {config['touches']}-touch email sequence for {len(out_recipients)} recipient(s) "
                f"({total} emails total), tone {config['tone']}, focus {config['focus']}.", "email")

    if name == "generate_linkedin_boolean":
        config = {
            "industry": args.get("industry", "") or analysis.get("company", ""),
            "roles": args.get("roles", []),
            "company_size": args.get("company_size", []),
            "geography": args.get("geography", ""),
            "keywords_include": args.get("keywords_include", ""),
            "keywords_exclude": args.get("keywords_exclude", ""),
        }
        result = pipeline.generate_boolean(username, analysis, config)
        storage.patch_campaign(cid, {
            "linkedin_config": config,
            "boolean_search": result["final"],
            "campaign_type": "linkedin",
            "current_step": 4,
            "status": "ready",
        }, username=username, sandbox=sandbox)
        return ("Generated a LinkedIn boolean search, connection message and Dripify drip sequence.", "linkedin")

    if name == "generate_abm_sequence":
        contacts = campaign.get("contacts") or campaign.get("recipients") or []
        config = {
            "account": args.get("account", "") or analysis.get("company", ""),
            "geography": args.get("geography", ""),
            "why_now": args.get("why_now", ""),
            "contacts": contacts,
        }
        result = pipeline.generate_abm_sequence(username, analysis, config, contacts)
        storage.patch_campaign(cid, {
            "abm_config": config,
            "abm_matrix": result["final"],
            "campaign_type": "abm",
            "current_step": 4,
            "status": "ready",
        }, username=username, sandbox=sandbox)
        return ("Generated a 4-week multi-channel ABM matrix (LinkedIn + email).", "abm")

    return (f"Unknown tool: {name}", None)


def campaign_chat(username: str, campaign: dict, messages: list[dict], sandbox: bool) -> dict:
    """Run one conversational turn. Returns {reply, generated, artifact_type}."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    system = _builder_system(username, campaign)

    convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("content")]
    reply_texts: list[str] = []
    artifact_type: str | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=system,
            tools=TOOLS,
            messages=convo,
        )
        log_cache_usage("lead.builder", resp.usage)

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if text:
            reply_texts.append(text)
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            break

        convo.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for tu in tool_uses:
            try:
                summary, kind = _execute_tool(tu.name, tu.input or {}, campaign, username, sandbox)
                if kind:
                    artifact_type = kind
                campaign = storage.get_campaign(campaign["id"], username=username, sandbox=sandbox) or campaign
            except Exception as e:
                summary = f"Generation failed: {e}"
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": summary})
        convo.append({"role": "user", "content": tool_results})

    return {
        "reply": "\n\n".join(reply_texts).strip() or "Done.",
        "generated": bool(artifact_type),
        "artifact_type": artifact_type,
    }
