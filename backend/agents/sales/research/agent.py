"""Research — the brief you read before you write anything.

Canon's contract: *deep research on the company as a whole plus the selected key
decision-maker(s) → one combined brief*. Company context, why timing matters now,
the product angle, then the person. No review gate: this is internal preparation,
and gating your own homework would only slow the person who asked for it.

Two things make it more than a web search.

**It starts from what the run already knows.** When Lead scoring has graded the
company, the whole verdict goes into the prompt — the signal strength, the inferred
product fit, the behaviour that drove the grade. The research then begins from the
real reason there is an opportunity instead of rediscovering it from a company name.
This is the same argument that justified paths existing at all.

**It writes back to Memory.** Canon says Research feeds Memory, and this is the
first agent that does: the account and its topic are recorded, so the next brief on
the same company — and every Owl conversation about it — starts warmer.

The product angle is grounded in the vault rather than left to the model's
recollection, because the portfolio is a fact about Acme and the vault is where
that fact lives.
"""
from __future__ import annotations

from agents.mind import memory
from agents.mind.registry import MODELS, Tier
from agents.sales import prompts
from agents.services import web_discovery
from agents.shared.vault import load_vault_for_product_rec

#: Web-search budget for one brief. Enough for the company, its timing and the
#: person; beyond this the returns fall off and the spend does not.
MAX_SEARCHES = 6
MAX_ROUNDS = 8
MAX_TOKENS = 4096

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {
            "type": "string",
            "description": "The company to research. Required.",
        },
        "person": {
            "type": "string",
            "description": (
                "Optional. The decision-maker to profile alongside the company — "
                "usually one the user picked from an X-ray shortlist."
            ),
        },
        "notes": {
            "type": "string",
            "description": "Optional. Anything the user wants the research to take account of.",
        },
    },
    "required": ["company"],
}


def _person_arg(person: dict | str | None) -> dict:
    """Accept a picked X-ray row or a bare name — conversation gives the latter."""
    if isinstance(person, str):
        return {"full_name": person.strip()} if person.strip() else {}
    return person or {}


def _system_with_portfolio(lead: dict | None) -> str:
    """The research system prompt, grounded in the real portfolio.

    Reuses `load_vault_for_product_rec`, the loader the product-recommendation path
    already uses, so "which products fit this situation" is answered from the vault
    rather than from whatever the model remembers about the range. When scoring has
    already inferred a fit, that product's docs are what get loaded.

    The vault is local, but a brief is still useful without the angle grounding, so
    a failure here degrades the brief instead of failing the run.
    """
    fit = ((lead or {}).get("product_fit") or "").strip()
    try:
        portfolio = load_vault_for_product_rec(product_name=fit or None)
    except Exception as e:  # pragma: no cover - local read, defensive only
        print(f"[research] vault angle grounding unavailable: {e}")
        return prompts.RESEARCH_SYSTEM

    if not portfolio.strip():
        return prompts.RESEARCH_SYSTEM
    return (
        f"{prompts.RESEARCH_SYSTEM}\n\n"
        "# The Acme portfolio\n\n"
        "Ground the angle in these products. Do not invent capabilities that are "
        "not described here.\n\n"
        f"{portfolio}"
    )


def _remember(username: str, company: str, brief: dict) -> None:
    """Record the account and what this brief was about.

    Best-effort on purpose: a memory write failing must not lose the brief the
    person is waiting for. It is logged, not raised.
    """
    try:
        account_id = memory.upsert_account(username, company, source="research")
        topic = (brief.get("timing") or {}).get("why_now") or ""
        if topic:
            memory.record_account_topic(
                username,
                account_id,
                topic,
                signal=", ".join((brief.get("timing") or {}).get("signals") or [])[:200],
            )
    except Exception as e:
        print(f"[research] memory write skipped: {e}")


def brief(
    username: str,
    *,
    company: str,
    person: dict | str | None = None,
    lead: dict | None = None,
    notes: str = "",
) -> dict:
    """Research a company and, when named, one of its decision-makers.

    Returns the brief with `company`/`timing`/`angle`/`person`/`risks`/`sources`,
    plus `error` when the turn did not complete cleanly. A partial brief is
    returned rather than raised: most of it is usually there, and discarding a
    truncated answer wastes the searches that produced it.
    """
    company = (company or "").strip()
    if not company:
        return {"error": "no_company", "company": {}, "timing": {}, "angle": {}, "person": {}}

    picked = _person_arg(person)

    turn = web_discovery.research_object(
        system=_system_with_portfolio(lead),
        user_message=prompts.research_user_prompt(
            company=company, person=picked, lead=lead, notes=notes,
        ),
        tool_choice={"type": "any"},
        max_uses=MAX_SEARCHES,
        # Sonnet per canon's contract, stated explicitly rather than inherited, so
        # the Opus upgrade canon allows for is a one-line change here.
        model=MODELS[Tier.SONNET],
        max_tokens=MAX_TOKENS,
        max_rounds=MAX_ROUNDS,
    )

    result = turn["result"] or {}
    out = {
        "subject": {"company": company, "person": picked.get("full_name") or picked.get("name") or ""},
        "company": result.get("company") or {},
        "timing": result.get("timing") or {},
        "angle": result.get("angle") or {},
        "person": result.get("person") or {},
        "risks": result.get("risks") or [],
        "sources": result.get("sources") or [],
        "error": turn["error"],
    }

    if out["company"] or out["timing"] or out["angle"]:
        _remember(username, company, out)
    return out


def run_as_tool(username: str, args: dict) -> str:
    """Research from conversation, reported in prose.

    Read-only with respect to the sales stores — it does not save a brief. Saving
    is the page's job, because a conversation is often exploratory and filling the
    brief list with half-asked questions would make it useless.
    """
    company = (args.get("company") or "").strip()
    if not company:
        return "Name a company to research."

    out = brief(
        username,
        company=company,
        person=args.get("person"),
        notes=(args.get("notes") or ""),
    )

    if out.get("error") and not out.get("company"):
        return f"Research on {company} found nothing usable ({out['error']})."

    lines = [f"**{company}**"]
    what = (out["company"] or {}).get("what_they_do")
    if what:
        lines.append(what)

    why_now = (out["timing"] or {}).get("why_now")
    if why_now:
        lines.append(f"\n**Why now** — {why_now}")

    angle = out["angle"] or {}
    if angle.get("fit"):
        products = ", ".join(angle.get("products") or [])
        lines.append(f"\n**Angle** — {angle['fit']}" + (f" ({products})" if products else ""))

    profile = out["person"] or {}
    if profile.get("name"):
        owns = f" — {profile['owns']}" if profile.get("owns") else ""
        lines.append(f"\n**{profile['name']}**, {profile.get('role') or 'role unknown'}{owns}")
        if profile.get("how_to_approach"):
            lines.append(f"Approach: {profile['how_to_approach']}")

    if out.get("risks"):
        lines.append("\n**Worth knowing** — " + "; ".join(out["risks"][:3]))

    sourced = len(out.get("sources") or [])
    lines.append(f"\n_{sourced} source{'' if sourced == 1 else 's'} cited. Nothing saved — open Research to keep this._")

    if out.get("error"):
        lines.append(f"_(The research turn ended early: {out['error']}. This brief may be incomplete.)_")

    return "\n".join(lines)
