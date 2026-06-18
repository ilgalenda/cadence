from __future__ import annotations
"""Shared Anthropic access for Cadence agents.

One process-wide client and ONE shared concurrency slot, so every agent that
calls Claude shares a single throttle and stays within the org TPM ceiling —
rather than each agent holding its own Semaphore (which multiplies real
concurrency and can blow the limit). Centralises the retry/backoff on rate
limits and the model-id constants too, so a model bump happens in one place.
"""
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

import anthropic

# Model ids — one place to bump them.
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"
OPUS = "claude-opus-4-7"

_RETRY_DELAYS = [10, 30, 60]  # seconds between retries on 429

# One heavy Claude operation at a time across ALL agents.
_SLOT = threading.Semaphore(1)

_client: Optional[anthropic.Anthropic] = None
_client_lock = threading.Lock()


def get_client() -> anthropic.Anthropic:
    """Return the shared Anthropic client, creating it once."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise RuntimeError("ANTHROPIC_API_KEY not set")
                _client = anthropic.Anthropic(api_key=api_key)
    return _client


@contextmanager
def slot():
    """Acquire the single shared heavy-operation slot for the duration.

    Use this around a streaming call (which can't go through `call_claude`):

        with anthropic_client.slot():
            with anthropic_client.get_client().messages.stream(...) as stream:
                ...
    """
    with _SLOT:
        yield


def call_claude(
    *,
    system: Any = None,
    messages: list[dict],
    model: str = SONNET,
    max_tokens: int = 1024,
    tools: Optional[list[dict]] = None,
) -> anthropic.types.Message:
    """Non-streaming Claude call with the shared throttle + retry/backoff on 429.

    Returns the raw Anthropic Message. Use `.content[0].text` for plain text,
    or `call_claude_text(...)` for the common case.
    """
    client = get_client()
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system is not None:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    last_err: Optional[Exception] = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            with _SLOT:
                return client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            last_err = e
            if attempt == len(_RETRY_DELAYS):
                raise
    raise last_err  # pragma: no cover — loop always returns or raises above


def call_claude_text(**kwargs) -> str:
    """Convenience wrapper: return the first text block, stripped."""
    msg = call_claude(**kwargs)
    return msg.content[0].text.strip() if msg.content else ""
