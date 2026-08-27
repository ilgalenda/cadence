"""GTM — find target companies for outbound.

One job: given an ICP, a vertical, or a seed company to find look-alikes of,
propose the accounts worth approaching. It proposes; **the user selects** — the
list is a review gate, not a queue that starts working on its own.

**Fast and deliberately unverified.** GTM proposes candidates from recall in a few
seconds; the checking happens downstream, where the path already puts it — the user
picks a company, and X-ray and the research brief (both of which do search the web)
establish whether it is real. Grounding GTM itself was tried and measured: the output
was excellent when it arrived, but it arrived about two times in five and took two to
five minutes, because a multi-minute non-streaming turn drops and an exhausted search
budget ends with no terminal text. A shortlist you cannot get beats nothing, but a
shortlist you can get and then check beats both.

The consequence is a duty of honesty, not just of speed: every entry carries what to
`check` and any `caveat`, and the page tells the user these are unverified.

**Gained the Signals layer in Phase 5.** When the user watches accounts, what
Signals has found is folded into the `notes` the prompt already reads as "a timing
signal to weight towards". With an empty watchlist the digest is empty and the prompt
is **byte-identical** to before Signals existed — the same guarantee Campaign
Intelligence and Gmail drafting were each built to preserve, so a feature nobody uses
costs nothing.
"""
from __future__ import annotations

from agents.mind import core as mind
from agents.mind import governor as mind_governor
from agents.sales import prompts
from agents.sales.refine import OwlRefiner
from agents.shared.jsonparse import parse_json

# Room for twelve candidates with a rationale, a check and a caveat each. The 2048
# this replaced was set before the entries carried a check or a caveat.
MAX_TOKENS = 4096


def identify(
    username: str,
    analysis: dict,
    config: dict,
    *,
    use_signals: bool = True,
) -> dict:
    """Propose target companies. Returns ``{final, claude_raw, owl_applied, error}``.

    `final` always carries `{companies, notes}` — the shape is normalised here, not
    trusted from the model. `error` is non-null when the answer could not be parsed,
    which is reported rather than raised so the caller can tell a broken answer from
    an empty one.

    `use_signals` folds the watchlist's recent findings into the notes. On by default
    because a signal the user is already tracking is the best available steer; off for
    a caller who wants the unweighted proposal.
    """
    analysis = _with_signals(username, analysis) if use_signals else analysis

    with mind_governor.slot():
        raw = mind.analyze(
            system=prompts.GTM_TARGETS_SYSTEM,
            messages=[{
                "role": "user",
                "content": prompts.gtm_targets_user_prompt(analysis, config),
            }],
            max_tokens=MAX_TOKENS,
        ).text

    parse_error = None
    try:
        first_pass = _normalise(parse_json(raw))
    except Exception as e:  # noqa: BLE001 — an unparseable answer is a reported failure
        # Reported, not raised. A 500 tells the user only that something broke; the
        # page can distinguish "the model answered badly" from "you asked for a
        # sector with no candidates" and say the right thing.
        parse_error = f"parse_failed: {e}"
        first_pass = _normalise(None)

    # Refining an empty list costs a Sonnet call and cannot add a company — the
    # refiner is explicitly forbidden from inventing one.
    refined = first_pass
    if first_pass["companies"]:
        refined = _normalise(
            OwlRefiner(username).refine(
                "gtm_targets", first_pass, {"analysis": analysis, "config": config},
            )
        )

    return {
        "final": refined,
        "claude_raw": first_pass,
        "owl_applied": refined != first_pass,
        "error": parse_error,
    }


def _normalise(result: object) -> dict:
    """Coerce a model result into the `{companies, notes}` contract every caller reads.

    The shape is guaranteed here rather than trusted from the model, because the
    bug this replaced was precisely a caller reading a key that was never present:
    a wrong shape must surface as an empty list, never as an AttributeError deep
    in a template.
    """
    if not isinstance(result, dict):
        return {"companies": [], "notes": ""}

    companies = result.get("companies")
    if not isinstance(companies, list):
        companies = []

    return {
        "companies": [c for c in companies if isinstance(c, (dict, str)) and c],
        "notes": str(result.get("notes") or ""),
    }


def _with_signals(username: str, analysis: dict) -> dict:
    """The same analysis, with the watchlist digest folded into its notes.

    Returns the input unchanged when there is nothing to add, so the prompt stays
    byte-identical for anyone not using the watchlist. Read-only and local — the
    digest never triggers a check, because a prompt builder that could spend a web
    search would make GTM's cost unpredictable.
    """
    try:
        from agents.sales.signals import agent as signals

        digest = signals.digest(username)
    except Exception as e:  # noqa: BLE001 — a steer failing must not cost the proposal
        print(f"[gtm] signals digest unavailable: {e}")
        return analysis

    if not digest:
        return analysis

    notes = str((analysis or {}).get("notes") or "").strip()
    return {**analysis, "notes": f"{digest}\n\n{notes}".strip() if notes else digest}


# ── As a tool Owl can run ───────────────────────────────────────────────────

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "vertical": {
            "type": "string",
            "description": "The vertical or ICP to target, e.g. 'finance', 'private 5G', 'defence'.",
        },
        "seed_company": {
            "type": "string",
            "description": "Optional. A company to find look-alikes of, instead of targeting by vertical.",
        },
        "notes": {
            "type": "string",
            "description": "Optional. Any extra constraint — geography, size, a timing signal to weight towards.",
        },
    },
}


def run_as_tool(username: str, args: dict) -> str:
    """Propose candidate companies from conversation. Read-only: the user still selects."""
    vertical = (args.get("vertical") or "").strip()
    seed = (args.get("seed_company") or "").strip()
    if not vertical and not seed:
        return "Give me a vertical to target, or a company to find look-alikes of."

    analysis = {"vertical": vertical, "seed_company": seed, "notes": args.get("notes") or ""}
    run = identify(username, analysis, {})
    companies = run["final"]["companies"]

    # A broken answer and an empty one are different answers and get different
    # advice. Blaming the query for a broken answer is how a broken agent goes
    # unnoticed for weeks.
    if not companies:
        if run["error"]:
            return f"That did not come back cleanly ({run['error']}). Worth trying again."
        return "No candidates came back for that. Try widening the vertical or naming a seed company."

    lines = []
    for company in companies[:12]:
        name = company.get("name") if isinstance(company, dict) else str(company)
        why = company.get("rationale") or company.get("why") or "" if isinstance(company, dict) else ""
        caveat = company.get("caveat") or "" if isinstance(company, dict) else ""
        lines.append(f"- {name}{f' — {why}' if why else ''}{f' (unsure: {caveat})' if caveat else ''}")

    more = f"\n…and {len(companies) - 12} more." if len(companies) > 12 else ""
    return (
        f"{len(companies)} candidates for {vertical or f'look-alikes of {seed}'}:\n"
        + "\n".join(lines) + more
        + "\n\n**Unverified** — these come from recall, not a search, so some may be "
        "acquired, renamed or wrong. X-ray or research a name before acting on it."
    )
