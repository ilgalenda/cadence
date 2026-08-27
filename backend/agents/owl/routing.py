from agents.mind.registry import MODELS, Tier

# Model IDs come from the Owl Core registry — the single source of truth for the
# model generation. `select_model` (the dynamic haiku<->sonnet router) is unchanged.
HAIKU_MODEL = MODELS[Tier.HAIKU]
SONNET_MODEL = MODELS[Tier.SONNET]

# Always routes to Sonnet — strong signal of analytical intent.
_STRONG_KEYWORDS = {
    "analyze", "analyse", "compare", "comparison", "strategy", "strategic",
    "explain", "difference between", "recommend", "recommendation", "should i",
    "help me understand", "walk me through", "what is the best",
    "architecture", "deployment", "implement", "integrate", "configure",
    "objection", "proposal", "competitive", "positioning",
    "prepare", "preparation",   # call/presentation prep is always non-trivial
    "sales",                    # sales cycle, sales pitch, sales context
    "linkedin",                 # LinkedIn outreach always requires Sonnet quality
}

# Weak signals: each one alone is not enough. Two or more in the same message → Sonnet.
# This prevents "What is PTP and why does it matter?" from over-triggering,
# while still catching "why does the protocol sequence matter for deployment?".
_WEAK_SIGNALS = {"why", "how does", "how do", "protocol", "sequence"}


def select_model(message: str) -> str:
    """Route to Haiku for simple lookups, Sonnet for analytical questions.

    Rules (evaluated in order):
    1. Message > 120 chars → Sonnet (anything over two sentences is non-trivial).
    2. Any strong analytical keyword present → Sonnet.
    3. Two or more weak signals present → Sonnet (combined context indicates depth).
    4. Default → Haiku.
    """
    if len(message) > 120:
        return SONNET_MODEL

    n = message.lower()

    for kw in _STRONG_KEYWORDS:
        if kw in n:
            return SONNET_MODEL

    weak_hits = sum(1 for kw in _WEAK_SIGNALS if kw in n)
    if weak_hits >= 2:
        return SONNET_MODEL

    return HAIKU_MODEL
