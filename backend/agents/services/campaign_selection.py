from __future__ import annotations
"""Campaign Selection capability service — deterministic, no LLM.

Given a lead's classification, compute the *eligible* campaign plan (archetype +
channel mix + touch structure) per the Campaign Playbook. The plan is a
proposal: the human always makes the final selection (via the Review gate).

Model (decided 2026-07-27, superseding the Playbook's three-archetype scheme):
**ABM is the standing outbound method**, so there are two archetypes —

  * ``warm_inbound_reengagement`` — the lead took an inbound action then went
    quiet. Email-first with a LinkedIn touch; touch count scales with warmth.
  * ``abm_account_push`` — every outbound case (a vertical-fit role, a cold
    prospect, or a whole-account signal). Coordinated LinkedIn + email + call
    over four weeks. When there is no named contact yet, identification (X-ray)
    is the campaign's first step, flagged by ``requires_identification``.

The Campaign Intelligence *outline* shapes the copy downstream; it is not an
input to this structural pick, which stays deterministic and testable.
"""
from dataclasses import dataclass, field

WARM_INBOUND = "warm_inbound_reengagement"
ABM = "abm_account_push"

SIGNAL_TYPES = {"inbound_action", "vertical_fit", "no_signal"}
STRENGTHS = {"hot", "warm", "cold"}

# Touch count scales with warmth (Campaign Playbook: hot 3, warm 4-5, cold 5).
_TOUCHES_BY_STRENGTH = {"hot": 3, "warm": 4, "cold": 5}

# The warm-inbound sequence, longest form. Fewer, warmer leads use a prefix of
# it: 3 = core three, 4 adds a new angle, 5 adds a break-up.
_INBOUND_SEQUENCE = ["warm_intro", "value_add", "soft_ask", "new_angle", "break_up"]

# The ABM four-week structure; the two channels are coordinated but never
# word-for-word identical.
_ABM_SEQUENCE = ["week1_connect", "week2_followup_email", "week3_value_add", "week4_soft_ask"]

_GRADE_TO_STRENGTH = {"A": "hot", "B": "warm", "C": "cold"}


@dataclass
class CampaignPlan:
    """The eligible campaign the human is offered for a lead."""

    archetype: str
    channels: list[str]
    touch_count: int
    cadence: str
    touch_structure: list[str]
    requires_identification: bool
    rationale: str
    inputs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def strength_from_grade(grade: str) -> str:
    """Map a lead-score grade (A/B/C) to signal strength (hot/warm/cold).

    A convenience bridge from the deterministic scorer; ``select_campaign`` still
    takes strength explicitly so callers can override.
    """
    try:
        return _GRADE_TO_STRENGTH[grade.strip().upper()]
    except (AttributeError, KeyError):
        raise ValueError(f"Unknown grade {grade!r}; expected one of {sorted(_GRADE_TO_STRENGTH)}")


def select_campaign(
    *,
    signal_type: str,
    signal_strength: str,
    has_named_contact: bool = True,
) -> CampaignPlan:
    """Compute the eligible campaign plan for a classified lead.

    Args:
        signal_type: 'inbound_action' | 'vertical_fit' | 'no_signal'.
        signal_strength: 'hot' | 'warm' | 'cold'.
        has_named_contact: whether a specific person is already identified.
            Only affects outbound (ABM): False means identify first.
    """
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"Unknown signal_type {signal_type!r}; expected one of {sorted(SIGNAL_TYPES)}")
    if signal_strength not in STRENGTHS:
        raise ValueError(f"Unknown signal_strength {signal_strength!r}; expected one of {sorted(STRENGTHS)}")

    inputs = {
        "signal_type": signal_type,
        "signal_strength": signal_strength,
        "has_named_contact": has_named_contact,
    }

    if signal_type == "inbound_action":
        touches = _TOUCHES_BY_STRENGTH[signal_strength]
        return CampaignPlan(
            archetype=WARM_INBOUND,
            channels=["email", "linkedin"],
            touch_count=touches,
            cadence="email-first, over 2-3 weeks; a LinkedIn touch alongside",
            touch_structure=_INBOUND_SEQUENCE[:touches],
            requires_identification=False,
            rationale=(
                f"Inbound action → warm re-engagement; {signal_strength} lead → {touches} touches, "
                "led by the specific action they took, with a LinkedIn touch as a second channel."
            ),
            inputs=inputs,
        )

    # Every outbound case runs as ABM, the standing method.
    requires_identification = not has_named_contact
    identification_note = (
        "no named contact yet → identify the right personas (X-ray) before outreach"
        if requires_identification
        else "named contact known → proceed to outreach"
    )
    return CampaignPlan(
        archetype=ABM,
        channels=["linkedin", "email", "call"],
        touch_count=len(_ABM_SEQUENCE),
        cadence="4 weeks, relationship-first; LinkedIn + email + call coordinated, not identical",
        touch_structure=list(_ABM_SEQUENCE),
        requires_identification=requires_identification,
        rationale=(
            f"{signal_type.replace('_', ' ')} → outbound, run as ABM (the standing method); "
            f"{identification_note}."
        ),
        inputs=inputs,
    )
