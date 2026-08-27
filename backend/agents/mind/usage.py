"""Rate-aware per-call usage logging.

Replaces the old single hard-coded Sonnet-4.6 rate table (formerly
`agents/shared/vault.py:log_cache_usage`), which mis-reported cost for every
non-Sonnet call. The Mind calls `record()` automatically after each request with
the model that actually ran, so the cost line is correct per tier.

Rates are USD per million tokens (standard list prices): cache writes bill at
1.25x input, cache reads at 0.1x input.
"""
from __future__ import annotations

from agents.mind.registry import Tier, tier_for

# Standard list prices, USD per million tokens (input, output).
_BASE_RATES: dict[Tier, tuple[float, float]] = {
    Tier.HAIKU: (1.00, 5.00),
    Tier.SONNET: (3.00, 15.00),
    Tier.OPUS: (5.00, 25.00),
}


def _rates(tier: Tier) -> dict[str, float]:
    inp, out = _BASE_RATES[tier]
    return {
        "input": inp,
        "output": out,
        "cache_write": inp * 1.25,
        "cache_read": inp * 0.10,
    }


def record(label: str, usage, model: str) -> None:
    """Print token counts and an estimated cost for one response, at `model`'s rate."""
    if usage is None:
        return
    try:
        created = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0

        rates = _rates(tier_for(model))
        total_input = inp + created + read
        total_tokens = total_input + out
        cost = (
            inp * rates["input"]
            + created * rates["cache_write"]
            + read * rates["cache_read"]
            + out * rates["output"]
        ) / 1_000_000

        print(
            f"[cache] {label} model={model} read={read} create={created} "
            f"input={inp} output={out} total_in={total_input} "
            f"total={total_tokens} cost=${cost:.4f}"
        )
    except Exception:
        pass
