from __future__ import annotations
"""Role-aware system-prompt assembly for the Onboarding agent.

Persona + the onboarding curriculum + the shared knowledge vault, with a
cache breakpoint so the (byte-stable) prefix hits the Anthropic prompt cache
across a conversation's turns. Reuses the same grounding the rest of the
platform uses (`load_vault_for_session`).
"""
from pathlib import Path

from agents.onboarding.prompts import ONBOARDING_PERSONA
from agents.shared.vault import load_vault_for_session

_CURRICULUM_PATH = Path(__file__).parent / "curriculum.md"


def _curriculum() -> str:
    try:
        return _CURRICULUM_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def normalise_role(role: str) -> str:
    """Map a free-form role to the onboarding track: 'sales' or 'ops'."""
    r = (role or "").lower()
    if any(k in r for k in ("sales", "gtm", "account", "sdr", "revenue", "founder")):
        return "sales"
    return "ops"


def onboarding_system_blocks(username: str, role: str) -> list[dict]:
    track = normalise_role(role)
    focus = (
        "sales / GTM workflows (Calls, Lead, Owl)"
        if track == "sales"
        else "operations workflows (platform structure, Duty & Tax, Forecasting, the knowledge vault)"
    )
    vault = load_vault_for_session(username)
    prefix = (
        ONBOARDING_PERSONA
        + f"\n\nThis user's onboarding focus: {focus}.\n\n"
        + "# Onboarding curriculum\n\n" + _curriculum()
        + "\n\n# Cadence Knowledge\n\n"
    )
    return [
        {"type": "text", "text": prefix + vault, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"\n\nYou are guiding {username} (track: {track})."},
    ]
