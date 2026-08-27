"""Model registry and per-task profiles — the single source of truth for which
model each task runs on and how it is configured.

This is where the model generation lives. Upgrading the whole platform is an
edit to `MODELS` here; nothing else hard-codes a model ID.

Model-generation note (Owl Core migration): the tiers are the current generation
(Haiku 4.5 / Sonnet 5 / Opus 4.8). On these models `budget_tokens` and non-default
sampling params are rejected, so the Mind never sends them. Sonnet 5 runs adaptive
thinking by *default* when `thinking` is omitted; to preserve the old thinking-off
behaviour (and keep the full max_tokens budget for the answer) every Sonnet/Opus
task sets thinking explicitly off in Phase 0. Haiku 4.5 does not take the thinking
config, so nothing is sent for it.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class Tier(enum.Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


# The one place model IDs live. Upgrade the platform by editing these.
MODELS: dict[Tier, str] = {
    Tier.HAIKU: "claude-haiku-4-5",
    Tier.SONNET: "claude-sonnet-5",
    Tier.OPUS: "claude-opus-4-8",
}


def tier_for(model_id: str) -> Tier:
    """Map an explicit model ID (e.g. from the dynamic chat router) back to its
    tier, so thinking/backoff rules can be derived for it.
    """
    for tier, mid in MODELS.items():
        if mid == model_id:
            return tier
    # Best-effort substring fallback for legacy/aliased IDs.
    lowered = model_id.lower()
    for tier in Tier:
        if tier.value in lowered:
            return tier
    raise ValueError(f"unknown model id: {model_id!r}")


# thinking: "off" -> {"type":"disabled"} on Sonnet/Opus; None -> omit (Haiku, and
# the tier-aware builder also omits for Haiku regardless of this value).
@dataclass(frozen=True)
class TaskProfile:
    tier: Tier
    default_max_tokens: int
    thinking: str | None  # "off" | "adaptive" | None
    long_backoff: bool    # apply the [10,30,60]s outer retry loop


TASK_PROFILES: dict[str, TaskProfile] = {
    # Haiku classifier — fast, cheap, no thinking config.
    "classify": TaskProfile(Tier.HAIKU, 400, None, long_backoff=False),
    # Sonnet composition — JSON out; thinking off keeps the budget for the answer.
    "compose": TaskProfile(Tier.SONNET, 2048, "off", long_backoff=True),
    # Sonnet analysis — large structured JSON.
    "analyze": TaskProfile(Tier.SONNET, 8192, "off", long_backoff=True),
    # Chat — tier is dynamic (router passes an explicit model); cap raised from
    # the old 1024 so long replies are not truncated. Streams, so no timeout risk.
    "chat": TaskProfile(Tier.SONNET, 8192, "off", long_backoff=False),
    # Web-search research — SONNET default (X-ray); OPUS passed explicitly for
    # high-intent detection.
    "research": TaskProfile(Tier.SONNET, 8192, "off", long_backoff=False),
}


def build_thinking(tier: Tier, want: str | None) -> dict | None:
    """Return the `thinking` request param for a tier, or None to omit it.

    Haiku 4.5 does not take the thinking config → always omit.
    """
    if tier is Tier.HAIKU:
        return None
    if want == "off":
        return {"type": "disabled"}
    if want == "adaptive":
        return {"type": "adaptive"}
    return None
