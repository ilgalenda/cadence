"""Acme Learning's surface — `/api/learn`.

The quizzes: the pool the Practice page works through, a generated certification
quiz, and the client-facing newsletter questions. Moved out of `agents/calls` in
Stage 4, which is where Phase 6 always said they belonged — *"moving the quiz code
out of the `calls` module into the new section"*.

The material comes from analysed calls, so this composes `sales/store/calls.py`.
That direction is deliberate: Learn reads what Sales produced, and nothing in Sales
reads back.

**Anonymisation is a rule here, not a habit.** The certification quiz is built from
real calls, so the scenarios are reduced to concepts, objections and signals before
they reach a prompt — never a company, never a person. The prompt repeats the rule;
two independent guards on the same thing.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.learn import prompts
from agents.mind import core as mind
from agents.sales.store import calls as store
from agents.shared import wiki
from agents.shared.jsonparse import parse_json_array
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/api/learn", tags=["learn"], dependencies=[Depends(require_authed)])

#: Bounds on what can be asked for. The floor stops a one-question "quiz"; the
#: ceiling stops a request that would run past the token cap and return nothing.
CERTIFICATION_RANGE = (5, 20)
NEWSLETTER_RANGE = (1, 3)

NEWSLETTER_MAX_TOKENS = 2048

#: A four-option MCQ with an explanation runs to roughly 200 tokens, so the cap
#: is derived from what was asked for rather than fixed. It was a flat 4096 for
#: any count in the range above, which is generous at five questions and short
#: at twenty — and a cut-off answer is not a smaller quiz, it is a broken one.
CERTIFICATION_TOKENS_PER_QUESTION = 400
CERTIFICATION_TOKENS_OVERHEAD = 512
CERTIFICATION_MAX_TOKENS_CEILING = 8192


def _certification_max_tokens(count: int) -> int:
    """Room for `count` questions, capped at what the tier will serve."""
    return min(
        CERTIFICATION_MAX_TOKENS_CEILING,
        CERTIFICATION_TOKENS_OVERHEAD + count * CERTIFICATION_TOKENS_PER_QUESTION,
    )

#: How many calls' worth of anonymised material the certification prompt carries.
MAX_SCENARIOS = 50


class GenerateQuizRequest(BaseModel):
    count: int = 10


class NewsletterQuizRequest(BaseModel):
    count: int = 1


def _analysed_calls(sandbox: bool) -> list[dict]:
    """Every analysed call, all users — the quiz pool is the team's, not one person's."""
    return [
        session for session in store.load_sessions(sandbox)
        if session.get("type") == "call_analysis" and isinstance(session.get("result"), dict)
    ]


def _clamp(value: int, bounds: tuple[int, int]) -> int:
    low, high = bounds
    return max(low, min(high, value))


def _strings(value) -> list[str]:
    return [item for item in (value or []) if isinstance(item, str) and item.strip()]


@router.get("/quiz/pool")
def quiz_pool(request: Request):
    """The questions already sitting in analysed calls, plus what they cover.

    Read-only and free: every question here came out of an analysis that was already
    paid for, which is why Practice can open without generating anything.
    """
    calls = _analysed_calls(is_sandbox(request))

    topics: Counter = Counter()
    quizzes = []
    total = 0

    for session in calls:
        result = session["result"]
        concepts = _strings(result.get("concepts_mentioned"))
        for concept in concepts:
            topics[concept.strip()] += 1

        flashcards = result.get("flashcards") or []
        if not isinstance(flashcards, list) or not flashcards:
            continue

        total += len(flashcards)
        quizzes.append({
            "id": session.get("id"),
            "title": session.get("title") or "Untitled call",
            "timestamp": session.get("timestamp") or "",
            "questions": flashcards,
            "concepts": [c.strip() for c in concepts],
        })

    return {
        "total_calls": len(calls),
        "total_questions": total,
        "top_topics": [{"term": term, "count": count} for term, count in topics.most_common(20)],
        "calls": quizzes,
    }


@router.post("/quiz/generate")
def generate_certification_quiz(req: GenerateQuizRequest, request: Request):
    """A generalised certification quiz, built from what the team has actually met."""
    count = _clamp(req.count, CERTIFICATION_RANGE)
    calls = _analysed_calls(is_sandbox(request))

    # Anonymised before it goes anywhere near a prompt: concepts, objections and
    # signals only. A company name in a certification question would leak a client
    # into a document that circulates internally without context.
    scenarios = []
    for session in calls:
        result = session["result"]
        entry: dict = {}
        for key in ("concepts_mentioned", "objections", "buying_signals"):
            values = _strings(result.get(key))
            if values:
                entry[key.replace("_mentioned", "")] = values

        recommendation = result.get("product_recommendation")
        if isinstance(recommendation, dict) and recommendation.get("reasoning"):
            entry["product_reasoning"] = recommendation["reasoning"]

        if entry:
            scenarios.append(entry)

    try:
        result = mind.compose(
            system=None,
            messages=[{
                "role": "user",
                "content": prompts.certification_quiz_prompt(
                    count=count,
                    products=wiki.products_reference(),
                    glossary=wiki.glossary_reference(),
                    scenarios=scenarios[:MAX_SCENARIOS],
                ),
            }],
            max_tokens=_certification_max_tokens(count),
        )
        questions = parse_json_array(result.text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Quiz generation failed: {e}")

    return {
        "questions": questions,
        # What was asked for, so the caller can tell a short batch from a whole
        # one. A truncated answer is salvaged rather than discarded upstream, and
        # a quiz of seven when ten were asked for is worth knowing about.
        "requested": count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_calls": len(calls),
    }


@router.post("/quiz/newsletter")
def generate_newsletter_quiz(req: NewsletterQuizRequest):
    """Client-facing educational questions for the newsletter.

    Draws on the glossary and the product range only — never on calls. The audience
    is outside the company, so there is no anonymisation problem to solve here:
    there is simply nothing from a call in it.
    """
    count = _clamp(req.count, NEWSLETTER_RANGE)

    try:
        result = mind.compose(
            system=None,
            messages=[{
                "role": "user",
                "content": prompts.newsletter_quiz_prompt(
                    count=count,
                    products=wiki.products_reference(),
                    glossary=wiki.glossary_reference(),
                ),
            }],
            max_tokens=NEWSLETTER_MAX_TOKENS,
        )
        questions = parse_json_array(result.text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Newsletter quiz generation failed: {e}")

    return {
        "questions": questions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
