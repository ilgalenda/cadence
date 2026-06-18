"""Shared helpers for parsing JSON out of model output.

Models often wrap JSON in a ```json fenced block or surround it with prose.
These helpers strip the common wrappers and, for arrays, fall back to slicing
the first ``[...]`` span. Kept in one place so a fix to the fence handling
applies everywhere it's used.
"""
from __future__ import annotations

import json


def parse_json(raw: str):
    """Parse a JSON value from model output, stripping a ```json fence if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    return json.loads(raw)


def parse_json_array(raw: str):
    """Best-effort JSON-array extraction; falls back to slicing the first [...] span."""
    try:
        return parse_json(raw)
    except Exception:
        pass
    if "[" in raw and "]" in raw:
        start = raw.index("[")
        end = raw.rindex("]") + 1
        try:
            return json.loads(raw[start:end])
        except Exception:
            pass
    raise ValueError("could not parse JSON array from model output")
