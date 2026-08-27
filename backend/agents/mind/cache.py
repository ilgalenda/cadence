"""Prompt-cache discipline helpers.

`cached_system` builds the canonical two-block system prompt: a stable prefix
carrying the ephemeral cache breakpoint, plus an optional volatile tail with no
cache_control (so it never invalidates the cached prefix). `plain_system` is the
analysis-style prompt with no caching, for prefixes that are per-request scoped.
"""
from __future__ import annotations


def cached_system(prefix: str, tail: str | None = None) -> list[dict]:
    """Stable `prefix` (cached) followed by an optional uncached `tail`."""
    blocks: list[dict] = [
        {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}
    ]
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks


def plain_system(*parts: str) -> list[dict]:
    """Join `parts` into system blocks with no cache_control (analysis-style)."""
    return [{"type": "text", "text": p} for p in parts if p]
