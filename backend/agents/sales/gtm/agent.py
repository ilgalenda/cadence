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

from pydantic import ValidationError

from agents.mind import core as mind
from agents.mind import governor as mind_governor
from agents.sales import prompts
from agents.sales.gtm import schemas
from agents.sales.refine import OwlRefiner
from agents.shared.jsonparse import parse_json, parse_json_object

# Room for twelve candidates with a rationale, a check and a caveat each. The 2048
# this replaced was set before the entries carried a check or a caveat.
MAX_TOKENS = 4096

#: Tracker mode's own budget. Twelve fields across ten to twelve accounts does not
#: fit the shortlist's 4096 — a truncated answer fails to parse and the whole run
#: is wasted, which costs more than the larger budget does.
TRACKER_MAX_TOKENS = 8192


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


def build_targets(
    username: str,
    analysis: dict,
    config: dict,
    *,
    use_signals: bool = True,
) -> dict:
    """Propose a **target list for a tracker**. Returns the same four-key contract.

    `final` is `{rows, notes}`, validated through `schemas.TargetList` rather than
    coerced. That is the difference from `identify`: a shortlist of names read by a
    person survives a missing field, and a list that gets priced and quoted does
    not — a row with no `deal_shape` is the difference between £300 and £1,000.

    **`identify` is untouched.** This is a second mode, not a changed one: its
    thirteen contract tests still describe the shortlist exactly as before, and a
    caller wanting names still gets names in forty seconds.

    **No refiner pass.** `refine.py:70` gives `gtm_targets` 2048 tokens, half what
    the first pass had and a quarter of what this mode needs; a truncated second
    pass fails to parse, is swallowed, and silently returns the first — so the
    refinement would be invisible whether or not it happened. Better not to spend
    the call.
    """
    digest = _digest(username) if use_signals else ""

    with mind_governor.slot():
        raw = mind.analyze(
            system=prompts.GTM_TRACKER_SYSTEM,
            messages=[{
                "role": "user",
                "content": prompts.gtm_tracker_user_prompt(analysis, config, digest),
            }],
            max_tokens=TRACKER_MAX_TOKENS,
        ).text

    try:
        # The lenient object path, not the strict one `identify` uses: this answer
        # is twice the size, and a single unquoted key in row two was observed
        # discarding a whole nine-account list.
        parsed = schemas.TargetList.model_validate(parse_json_object(raw))
    except ValidationError as e:
        # Reported, not raised, and the message names the field: a list refused
        # for one bad row must tell the person which row and why, or the only
        # remedy is to run it again and hope.
        return {
            "final": schemas.empty(),
            "claude_raw": None,
            "owl_applied": False,
            "error": f"invalid_target_list: {_first_problem(e)}",
        }
    except Exception as e:  # noqa: BLE001 — an unparseable answer is a reported failure
        return {
            "final": schemas.empty(),
            "claude_raw": None,
            "owl_applied": False,
            "error": f"parse_failed: {e}",
        }

    return {
        "final": parsed.model_dump(),
        "claude_raw": parsed.model_dump(),
        "owl_applied": False,
        "error": None,
    }


def _first_problem(error: ValidationError) -> str:
    """The first validation failure, as a sentence naming where it was."""
    problems = error.errors()
    if not problems:
        return "the answer did not match the target-list shape"
    first = problems[0]
    where = ".".join(str(part) for part in first.get("loc", ())) or "the list"
    return f'{where}: {first.get("msg", "invalid")}'


def _digest(username: str) -> str:
    """The watchlist findings, as their own block — or nothing.

    Read separately from `_with_signals`, which folds the digest into `notes`. In
    tracker mode it must stay identifiable: this mode may take a *trigger* from the
    watchlist, and a steer somebody typed by hand must not become one.
    """
    try:
        from agents.sales.signals import agent as signals

        return signals.digest(username)
    except Exception as e:  # noqa: BLE001 — a steer failing must not cost the proposal
        print(f"[gtm] signals digest unavailable: {e}")
        return ""


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


TRACKER_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "vertical": {
            "type": "string",
            "description": "The vertical or ICP to build the list from.",
        },
        "seed_company": {
            "type": "string",
            "description": "A company to find look-alikes of. Excluded from the list itself.",
        },
        "notes": {
            "type": "string",
            "description": "Any steer: a geography, a product angle, a segment to avoid.",
        },
    },
}


def run_as_tool_tracker(username: str, args: dict) -> str:
    """Build a target list for a tracker, as Owl runs it.

    Returns prose because Owl streams prose. The list is **queued for review**, not
    put on a tracker: this is the tool that writes, and what it writes is a request
    for a decision. Owl saying "done" about accounts nobody has read would be the
    one thing the review gate exists to prevent.
    """
    args = args or {}
    analysis = {
        "vertical": str(args.get("vertical") or "").strip(),
        "seed_company": str(args.get("seed_company") or "").strip(),
        "notes": str(args.get("notes") or "").strip(),
    }
    if not any(analysis.values()):
        return (
            "Say what to build the list from — a vertical, an ICP, or a company to "
            "find look-alikes of. Without a scope the list would be a guess."
        )

    result = build_targets(username, analysis, {})
    if result["error"]:
        return f"The list could not be built: {result['error']}"

    rows = result["final"]["rows"]
    if not rows:
        return "No accounts came out of that scope. Try naming a vertical."

    from agents.sales.gtm import review as gtm_review

    item = gtm_review.submit(username, result["final"], analysis)

    tiers = {1: 0, 2: 0, 3: 0}
    for row in rows:
        tiers[row["tier"]] = tiers.get(row["tier"], 0) + 1
    untriggered = sum(1 for row in rows if not row["trigger_text"])
    unshaped = sum(1 for row in rows if not row["deal_lines"])

    lines = [
        f"{len(rows)} accounts proposed and queued for your review "
        f"(tier 1: {tiers[1]}, tier 2: {tiers[2]}, tier 3: {tiers[3]}).",
        "",
    ]
    for row in rows:
        trigger = row["trigger_text"] or "no live trigger"
        lines.append(f"- **{row['account']}** — {row['segment']}, {row['campaign']}. {trigger}.")

    lines.append("")
    if untriggered:
        lines.append(
            f"{untriggered} of them carry no trigger, because nothing on the Signals "
            "watchlist covers them. Watching the tracker is what fills that column in."
        )
    if unshaped:
        lines.append(
            f"{unshaped} could not be given a deal shape, so they will land unpriced "
            "rather than priced on a guess."
        )
    lines.append(
        f"Nothing is on a tracker yet. Approve review item `{item['id']}` to create one."
    )
    return "\n".join(lines)
