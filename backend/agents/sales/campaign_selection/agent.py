"""Campaign Selection — the shape of the campaign, before anyone writes a word.

Canon's contract: *compute the eligible campaign per the Campaign Playbook; the
user selects*. Deterministic, like Lead scoring — there is **no LLM call anywhere
in this module**. The archetype, the channel mix, the touch count and the four-week
structure are rules, and a model that could move them would make them arbitrary.

**The selection is the gate.** Canon says the human step *is* the choosing, so
there is no review queue to file into and nothing to persist: recomputing the same
plan from the same lead costs nothing, and a stored plan would only go stale
against a playbook that changes.

`agents/services/campaign_selection.py` holds the rules. This module's job is the
seam either side of them: turning what Lead scoring actually produced into the
inputs those rules demand, and reporting anything it had to assume.

**Why the seam needs care.** The scoring analysis is written by a model, and it
emits prose — `"Inbound action"`, `"Vertical fit"`, `"No signal"`. The service
takes `inbound_action` / `vertical_fit` / `no_signal` and **raises on anything
else**. Left implicit, a stray capital letter would either crash a path step or,
worse, be silently read as "no signal" and quietly pick the wrong archetype. So
normalisation is explicit here, and every fallback is named in `assumed` — a plan
that guessed its own inputs and did not say so is worse than one that admits it.
"""
from __future__ import annotations

from agents.services import campaign_selection as rules

#: The strength used when nothing in the lead says how warm it is. `cold` gives the
#: longest sequence, which is the safe way to be wrong: a cold plan for a hot lead
#: wastes touches, a hot plan for a cold one drops the follow-ups that win it.
DEFAULT_STRENGTH = "cold"

#: The signal type used when the lead does not say. `no_signal` selects ABM — the
#: standing outbound method — which is what "we are going after them and nothing
#: has happened yet" means.
DEFAULT_SIGNAL_TYPE = "no_signal"

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "signal_type": {
            "type": "string",
            "enum": sorted(rules.SIGNAL_TYPES),
            "description": (
                "How the lead arose: inbound_action if they did something on our side, "
                "vertical_fit if we picked them for matching the ICP, no_signal for cold. "
                "Defaults to no_signal."
            ),
        },
        "signal_strength": {
            "type": "string",
            "enum": sorted(rules.STRENGTHS),
            "description": "How warm the lead is. Defaults to cold when unknown.",
        },
        "has_named_contact": {
            "type": "boolean",
            "description": (
                "Whether a specific person is already identified. False means the "
                "campaign starts by identifying one (X-ray). Defaults to false."
            ),
        },
    },
    "required": [],
}


def _canonical(value) -> str:
    """Lower-case and underscore-separate, so prose and enum values compare equal.

    `"Inbound action"`, `"inbound-action"` and `"INBOUND_ACTION"` all name the same
    thing; only the last is what the rules accept.
    """
    return "_".join(str(value or "").strip().lower().replace("-", " ").split())


def normalise_signal_type(value) -> tuple[str, bool]:
    """The lead's signal type as the rules expect it, and whether it was assumed."""
    canonical = _canonical(value)
    if canonical in rules.SIGNAL_TYPES:
        return canonical, False
    return DEFAULT_SIGNAL_TYPE, True


def normalise_strength(value, *, grade=None) -> tuple[str, bool]:
    """The lead's strength as the rules expect it, and whether it was assumed.

    Prefers what the analysis said; falls back to the deterministic score's grade
    through the service's own `strength_from_grade`, so the two never disagree
    about what a B means.
    """
    canonical = _canonical(value)
    if canonical in rules.STRENGTHS:
        return canonical, False

    if grade:
        try:
            return rules.strength_from_grade(str(grade)), True
        except ValueError:
            pass
    return DEFAULT_STRENGTH, True


def select(
    *,
    lead: dict | None = None,
    signal_type: str = "",
    signal_strength: str = "",
    has_named_contact: bool | None = None,
) -> dict:
    """Compute the eligible campaign for a lead.

    `lead` is Lead scoring's whole verdict, which is what a path hands over; the
    three explicit arguments override it and are what a conversation supplies.

    Returns the plan as a dict plus `assumed` — the inputs that were defaulted
    rather than read. Never raises: the rules reject unknown inputs, and this is
    the layer whose job is to make sure they never see one.
    """
    lead = lead or {}
    assumed: list[str] = []

    resolved_type, guessed_type = normalise_signal_type(
        signal_type or lead.get("signal_type")
    )
    if guessed_type:
        assumed.append("signal_type")

    resolved_strength, guessed_strength = normalise_strength(
        signal_strength or lead.get("signal_strength"),
        grade=lead.get("lead_grade"),
    )
    if guessed_strength:
        assumed.append("signal_strength")

    if has_named_contact is None:
        has_named_contact = False
        assumed.append("has_named_contact")

    plan = rules.select_campaign(
        signal_type=resolved_type,
        signal_strength=resolved_strength,
        has_named_contact=bool(has_named_contact),
    )

    return {**plan.to_dict(), "assumed": assumed, "error": None}


def run_as_tool(username: str, args: dict) -> str:
    """Select from conversation, reported in prose.

    Deterministic and read-only: it computes, and the person chooses. What it
    assumed is stated, because in conversation the inputs are usually thinner than
    in a path and the plan should not read as more informed than it is.
    """
    plan = select(
        signal_type=(args.get("signal_type") or ""),
        signal_strength=(args.get("signal_strength") or ""),
        has_named_contact=args.get("has_named_contact"),
    )

    archetype = "ABM account push" if plan["archetype"] == rules.ABM else "warm inbound re-engagement"
    channels = " · ".join(plan["channels"])

    lines = [
        f"**{archetype}** — {plan['touch_count']} touches across {channels}.",
        f"\n{plan['cadence']}.",
        "\n**The sequence**\n" + "\n".join(
            f"{n}. {step.replace('_', ' ')}" for n, step in enumerate(plan["touch_structure"], start=1)
        ),
        f"\n_{plan['rationale']}_",
    ]

    if plan["requires_identification"]:
        lines.append(
            "\n**No named contact yet**, so the campaign opens by finding one — run X-ray first."
        )

    if plan["assumed"]:
        stated = ", ".join(item.replace("_", " ") for item in plan["assumed"])
        lines.append(
            f"\n_Assumed: {stated}. Score the lead first and the plan is computed from "
            "what it actually found rather than the safe default._"
        )

    lines.append("\n_This is the eligible plan — the choice is yours to make._")
    return "\n".join(lines)
