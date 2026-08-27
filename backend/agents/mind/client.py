"""The one Anthropic client for the whole backend, plus the shared retry loop.

No agent constructs its own `anthropic.Anthropic` any more — they all go through
`get_client()`. The SDK already auto-retries 429/5xx a couple of times;
`with_backoff` is the outer long-tail loop (the old hand-rolled [10,30,60]s
pattern) applied only to the profiles that had it, now also covering overloaded
and timeout errors, not just rate limits.
"""
from __future__ import annotations

import os
import time
from typing import Callable, TypeVar

import anthropic

_CLIENT: anthropic.Anthropic | None = None

# Errors worth waiting out on the slow outer loop (the SDK handles fast retries).
RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APITimeoutError,
)

_DEFAULT_DELAYS = (10, 30, 60)

T = TypeVar("T")


def get_client() -> anthropic.Anthropic:
    """Return the process-wide Anthropic client, building it once."""
    global _CLIENT
    if _CLIENT is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _CLIENT = anthropic.Anthropic(api_key=api_key)
    return _CLIENT


def _reset_client_for_tests() -> None:
    """Clear the singleton so a patched `anthropic.Anthropic` is picked up."""
    global _CLIENT
    _CLIENT = None


def with_backoff(
    fn: Callable[[], T],
    *,
    delays: tuple[int, ...] = _DEFAULT_DELAYS,
    on: tuple[type[Exception], ...] = RETRYABLE,
) -> T:
    """Run `fn`, retrying on `on` errors after each of `delays` seconds.

    The first attempt is immediate; a final failure re-raises the last error.
    """
    last_err: Exception | None = None
    for attempt, delay in enumerate((0, *delays)):
        if delay:
            time.sleep(delay)
        try:
            return fn()
        except on as e:  # noqa: B902 - `on` is a tuple of exception types
            last_err = e
            if attempt == len(delays):
                raise
    assert last_err is not None  # unreachable; loop always returns or raises
    raise last_err
