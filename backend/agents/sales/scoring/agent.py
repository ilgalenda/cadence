"""Lead Scoring — the behavioural read of a lead.

One job: given what a visitor did, say how hot they are and why. The score
itself is **deterministic** (`services.lead_scoring`) so it is reproducible and
tunable; the model's part is only to read the raw signal into a structured
analysis. Those two halves are kept apart deliberately — a model that could move
the number would make the number meaningless.

Order matters and is locked by test: the analysis is refined first, then scored,
so the score reflects the corrected reading rather than the first pass.
"""
from __future__ import annotations

import json

from agents.mind import core as mind
from agents.mind import governor as mind_governor
from agents.sales import prompts
from agents.sales.refine import OwlRefiner
from agents.sales.store import scores
from agents.services import lead_scoring
from agents.shared.jsonparse import parse_json

SIGNAL_MAX_TOKENS = 1024


def _analyse_raw(user_prompt: str, image_b64: str | None, image_media_type: str | None):
    images = None
    if image_b64:
        images = [{"data": image_b64, "media_type": image_media_type or "image/png"}]
    result = mind.analyze(
        system=prompts.CLAUDE_BASE_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
        images=images,
        max_tokens=SIGNAL_MAX_TOKENS,
    )
    return result.text


def analyse(
    username: str,
    *,
    text: str | None = None,
    structured: dict | None = None,
    image_b64: str | None = None,
    image_media_type: str | None = None,
) -> dict:
    """Read a lead signal and attach its behavioural score.

    Returns ``{final, claude_raw, owl_applied}`` — the refined analysis carrying
    ``lead_score`` / ``lead_max_score`` / ``lead_grade`` / ``lead_thresholds`` /
    ``score_breakdown`` / ``score_signals`` / ``score_page_views``, the unrefined first pass, and whether
    refinement changed anything.

    The score is also filed to ``store.scores`` on the way out, so the grade bands
    have a distribution to be calibrated against.
    """
    with mind_governor.slot():
        raw = _analyse_raw(
            prompts.claude_signal_prompt(text, structured), image_b64, image_media_type
        )
        first_pass = parse_json(raw)

        lead_blob = json.dumps({"text": text, "structured": structured}, indent=2)
        refined = OwlRefiner(username).refine("signal", first_pass, {"lead_blob": lead_blob})
        owl_applied = refined != first_pass

        # Refinement can return non-dict JSON; the score keys need a mutable
        # mapping, so fall back to the first pass rather than losing the read.
        if not isinstance(refined, dict):
            refined = first_pass if isinstance(first_pass, dict) else {}
            owl_applied = False

        score = lead_scoring.score_lead(text, structured, refined)
        refined["lead_score"] = score["score"]
        refined["lead_max_score"] = score["max_score"]
        refined["lead_grade"] = score["grade"]
        refined["lead_thresholds"] = score["thresholds"]
        refined["score_breakdown"] = score["breakdown"]
        refined["score_signals"] = score["signals"]
        # The components say how much each part contributed; these say what was
        # actually visited. Dropping them would leave "2 page(s) of real
        # interest" with no way to see which two.
        refined["score_page_views"] = score["page_views"]

        # Kept so the grade bands can be re-fitted to a real distribution later;
        # never at the cost of the read itself, which is what the caller asked
        # for. A store that cannot be written is not a reason to fail a score.
        try:
            scores.record(username, score, company=str(refined.get("company") or ""))
        except Exception:  # noqa: BLE001
            pass

        return {"final": refined, "claude_raw": first_pass, "owl_applied": owl_applied}


# ── As a tool Owl can run ───────────────────────────────────────────────────

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {
            "type": "string",
            "description": "The raw lead signal — pasted visit data, form text, or a description of what the visitor did.",
        },
    },
    "required": ["signal"],
}


def run_as_tool(username: str, args: dict) -> str:
    """Score a lead from conversation. Read-only: it reports, it persists nothing."""
    signal = (args.get("signal") or "").strip()
    if not signal:
        return "No signal was given, so there is nothing to score."

    result = analyse(username, text=signal)["final"]
    grade = result.get("lead_grade", "?")
    score = result.get("lead_score", "?")
    company = result.get("company") or "the visitor"
    reasons = ", ".join(result.get("score_signals") or []) or "no specific behavioural signals"

    return (
        f"{company}: grade {grade}, score {score}. "
        f"Driven by {reasons}. "
        "The score is deterministic — the same behaviour always yields the same grade."
    )
