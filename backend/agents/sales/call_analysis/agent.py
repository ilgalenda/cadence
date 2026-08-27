"""Call Analysis — a transcript, read the way a sales colleague would read it.

Canon's contract: *pasted transcript → structured read: summary, buying signals,
objections, talking points, product-fit*. Trigger: the user pastes a transcript
(Granola transcribes externally). No review gate — it is a reading, not something a
customer sees.

Migrated out of `agents/calls` in Stage 4. Two things changed in the move.

**It stopped doing three other agents' jobs.** The old `run_call_analysis` analysed
the transcript *and* wrote learnings to the vault *and* wrote new glossary terms —
Knowledge Capture's work, done inline and ungated. That now belongs to
`sales/knowledge_capture`, which this module calls once and does not depend on: a
failure to file learnings must not lose the analysis the person is waiting for.

**It became reachable two ways.** It had a page but had never been an Owl tool, so
"analyse this call" was the one agent you could not ask for.

The vault prefix here is **transcript-scoped and deliberately uncached**
(`load_vault_for_analysis`): the scoped prefix differs per call, so caching would buy
the 1.25x write surcharge and no read benefit. That reasoning moved with the code
because it is the reason the prefix is ~30k tokens rather than ~130k.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.mind import core as mind
from agents.mind import persona
from agents.sales import prompts
from agents.sales.store import calls as store
from agents.shared.jsonparse import parse_json_object
from agents.shared.vault import load_vault_for_analysis, load_vault_for_product_rec

ANALYSIS_MAX_TOKENS = 8192
PRODUCT_FIT_MAX_TOKENS = 2048

#: The shape a failed parse still has to satisfy, so every reader downstream — the
#: page, the quiz pool, Recap — can assume the keys exist.
EMPTY_ANALYSIS = {
    "buying_signals": [],
    "objections": [],
    "talking_points": [],
    "concepts_mentioned": [],
    "summary": "",
    "knowledge_extracts": [],
    "flashcards": [],
    "new_terms": [],
}

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {
            "type": "string",
            "description": "The call transcript to read. Required.",
        },
        "title": {
            "type": "string",
            "description": "What to file the call as. Defaults to a dated label.",
        },
    },
    "required": ["transcript"],
}


def _first_name(username: str, name: str = "") -> str:
    return (name or username or "the user").split()[0]


def _system_blocks(username: str, transcript: str, name: str = "") -> list[dict]:
    """The analyser's system prompt over a transcript-scoped vault. Not cached."""
    return persona.system_blocks(
        role_overlay=prompts.CALL_ANALYSIS_ROLE,
        vault_knowledge=load_vault_for_analysis(transcript),
        tail=prompts.call_identity_tail(_first_name(username, name), ""),
        cache=False,
    )


def analyse(
    username: str,
    *,
    transcript: str,
    title: str = "",
    name: str = "",
    role: str = "",
    sandbox: bool = False,
    capture: bool = True,
) -> dict:
    """Read a transcript, file it, and stage what it taught us.

    Returns `{"id", **analysis, "error"}`. A transcript that could not be parsed
    still returns the full key set with `error` set, because the page, the quiz pool
    and Recap all index into these keys and a missing one would break them rather
    than degrade them.

    `capture=False` skips the Knowledge Capture hand-off — used by the conversational
    path, where an exploratory read should not stage vault entries.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return {"id": "", **EMPTY_ANALYSIS, "error": "no_transcript"}

    label = (title or "").strip() or f"Call — {datetime.now(timezone.utc).strftime('%d %b %Y')}"
    error = None

    try:
        result = mind.analyze(
            system=_system_blocks(username, transcript, name),
            messages=[{
                "role": "user",
                "content": prompts.call_analysis_prompt(
                    transcript=transcript, name=_first_name(username, name),
                ),
            }],
            max_tokens=ANALYSIS_MAX_TOKENS,
        )
        analysis = parse_json_object(result.text)
        if not isinstance(analysis, dict):
            raise ValueError("analysis was not an object")
    except Exception as e:
        print(f"[call-analysis] could not read the transcript: {e}")
        # The reading is lost, but the call is still filed — otherwise the person
        # has pasted a transcript and has nothing at all to show for it.
        analysis = dict(EMPTY_ANALYSIS)
        error = f"analysis_failed: {e}"

    filled = {**EMPTY_ANALYSIS, **analysis}

    session_id = _file(username, label, filled, transcript, sandbox)

    if capture:
        _stage_learnings(username, session_id, label, filled, sandbox)

    return {"id": session_id, **filled, "error": error}


def _file(username: str, title: str, analysis: dict, transcript: str, sandbox: bool) -> str:
    """Save the call and return its id."""
    from agents.sales.store._json import new_id

    call_id = new_id()
    store.save_session(
        {
            "id": call_id,
            "title": title,
            "type": "call_analysis",
            "timestamp": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M"),
            "result": analysis,
            # Kept so Owl can deep-dive the call on demand — analysis first,
            # transcript when asked.
            "transcript": transcript,
        },
        username,
        sandbox,
    )
    return call_id


def _stage_learnings(username: str, call_id: str, title: str, analysis: dict, sandbox: bool) -> None:
    """Hand what the call taught us to Knowledge Capture.

    Best-effort on purpose, and the reason this agent no longer does the work
    itself: staging is a separate job with its own gate, and a failure in it must
    not cost the analysis somebody is waiting for.
    """
    try:
        from agents.sales.knowledge_capture import agent as knowledge_capture

        knowledge_capture.capture(
            username,
            call_id=call_id,
            call_title=title,
            extracts=analysis.get("knowledge_extracts") or [],
            terms=analysis.get("new_terms") or [],
            sandbox=sandbox,
        )
    except Exception as e:
        print(f"[call-analysis] knowledge capture skipped: {e}")


def product_fit(
    username: str,
    *,
    call_id: str,
    product_name: str = "",
    sandbox: bool = False,
) -> dict:
    """Best-fit products for an already-analysed call.

    Runs against the stored *analysis* rather than the transcript, with a focused
    product vault — a fraction of the full read's cost, which is why it is opt-in
    rather than part of every analysis. Patches the stored result in place.

    Raises `KeyError` when the call is not this user's, and `ValueError` when it has
    no usable reading to work from — the route turns those into 404 and 422.
    """
    session = store.get_session(call_id, username, sandbox=sandbox)
    if session is None or session.get("type") != "call_analysis":
        raise KeyError(call_id)

    analysis = session.get("result")
    if not isinstance(analysis, dict):
        raise ValueError("that call has no usable analysis")

    concepts = [c for c in (analysis.get("concepts_mentioned") or []) if isinstance(c, str)]

    result = mind.analyze(
        system=persona.system_blocks(
            role_overlay=prompts.CALL_ANALYSIS_ROLE,
            vault_knowledge=load_vault_for_product_rec(
                product_name=product_name or None, concepts=concepts,
            ),
            tail=prompts.call_identity_tail(_first_name(username), ""),
            cache=False,
        ),
        messages=[{
            "role": "user",
            "content": prompts.product_fit_prompt(
                analysis=analysis, product_name=product_name,
            ),
        }],
        max_tokens=PRODUCT_FIT_MAX_TOKENS,
    )
    recommendation = parse_json_object(result.text)

    analysis["product_recommendation"] = recommendation
    session["result"] = analysis
    store.replace_session(call_id, username, session, sandbox=sandbox)
    return recommendation


def run_as_tool(username: str, args: dict) -> str:
    """Read a transcript from conversation, reported in prose.

    Files the call — a transcript is worth keeping and re-pasting it is tedious —
    but does **not** stage learnings: a conversation is often exploratory, and
    filling the vault from a half-considered paste is how the vault gets worse.
    """
    transcript = (args.get("transcript") or "").strip()
    if not transcript:
        return "Paste the transcript and I will read it."

    out = analyse(
        username,
        transcript=transcript,
        title=(args.get("title") or ""),
        capture=False,
    )

    if out["error"]:
        return f"I could not read that transcript ({out['error']})."

    lines = [f"**{out.get('summary') or 'Read the call.'}**"]

    for heading, key in (
        ("Buying signals", "buying_signals"),
        ("Objections", "objections"),
        ("Talking points", "talking_points"),
    ):
        items = [str(x).strip() for x in (out.get(key) or []) if str(x).strip()]
        if items:
            lines.append(f"\n**{heading}**\n" + "\n".join(f"- {x}" for x in items[:5]))

    lines.append(
        "\n_Filed to the call library. Nothing was added to the knowledge base — "
        "open Call analysis to stage what this taught us._"
    )
    return "\n".join(lines)
