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


def _decoded_arrays(raw: str):
    """Yield every JSON array that decodes cleanly somewhere in ``raw``.

    Each ``[`` is offered to the standard decoder, which stops of its own accord
    at the value's end. That is what makes this robust where slicing is not:
    ``raw_decode`` understands strings and escapes, so a ``\\"`` inside a field
    (routine in a search query) cannot throw off the bracket accounting, and
    prose on either side of the array is simply never entered. Hand-rolled
    matching gets this wrong in one direction or the other.

    Only outermost arrays are offered: once one decodes, the scan resumes past
    its end, so a nested field like ``"tags": ["a", "b"]`` is never mistaken for
    the payload it sits inside.
    """
    decoder = json.JSONDecoder()
    index = raw.find("[")
    while index != -1:
        try:
            value, end = decoder.raw_decode(raw, index)
        except ValueError:
            value, end = None, index
        if isinstance(value, list):
            yield value
            index = raw.find("[", max(end, index + 1))
            continue
        index = raw.find("[", index + 1)


def _salvage_truncated_array(raw: str):
    """Recover the complete elements of an array whose closing bracket is missing.

    A response cut off by ``max_tokens`` is a well-formed prefix: several whole
    objects, then half of one, and no ``]``. The outermost array therefore fails
    to decode, and without this the first array that *does* decode is a nested
    one — ``options``, ``tags``, whatever the objects happen to carry. Returning
    that is worse than returning nothing, because the caller receives a list of
    the right type and entirely the wrong meaning, then reports "nothing usable"
    for what is really a truncated answer.

    Returns ``None`` when the outermost array is intact (there is nothing to
    salvage, and the ordinary path must keep its behaviour) or when not even one
    element completed (there is nothing worth handing back).
    """
    start = raw.find("[")
    if start == -1:
        return None

    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(raw, start)
        if isinstance(value, list):
            return None
    except ValueError:
        pass

    items = []
    index = start + 1
    while index < len(raw):
        while index < len(raw) and raw[index] in ", \t\r\n":
            index += 1
        if index >= len(raw):
            break
        try:
            value, index = decoder.raw_decode(raw, index)
        except ValueError:
            break  # the half-written element the cut-off landed in
        items.append(value)

    return items or None


def parse_json_array(raw: str):
    """Best-effort JSON-array extraction from model output.

    Where a turn contains more than one array — an illustrative shape in the
    narration, a nested field, then the real payload — the richest one wins.
    A model that narrates around its answer, or restates a schema before
    filling it, otherwise loses the payload to whichever bracket came first.
    """
    try:
        parsed = parse_json(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Checked before the candidates below: an unterminated outermost array is
    # unambiguously the payload being cut off, so its complete elements beat any
    # nested array that happens to decode whole.
    salvaged = _salvage_truncated_array(raw)
    if salvaged:
        return salvaged

    candidates = list(_decoded_arrays(raw))
    if candidates:
        return max(candidates, key=len)
    raise ValueError("could not parse JSON array from model output")


def _quote_bare_keys(raw: str) -> str:
    """Put quotes round object keys a model left bare.

    Sonnet writing a long object occasionally drops the quotes on a single key —
    ``geography: "Sweden"`` in the middle of an otherwise perfect three-thousand
    token answer — and strict JSON discards the whole thing for it. One slip
    costing an entire run is the wrong trade when the slip is unambiguous.

    Scanned rather than regexed, because the repair must never reach inside a
    string: a note reading ``the site: Madrid`` is prose and must be left exactly
    as written. So this tracks string state and escapes, and only acts where a key
    is syntactically expected — immediately after ``{`` or after a ``,`` that is
    inside an object rather than an array.

    Conservative by construction: it inserts quotes and changes nothing else, so a
    string it cannot repair simply fails to parse as it did before.
    """
    out: list[str] = []
    # What each open bracket is, innermost last. A comma means "a key follows"
    # only inside an object.
    stack: list[str] = []
    in_string = False
    escaped = False
    expecting_key = False
    index = 0

    while index < len(raw):
        char = raw[index]

        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            expecting_key = False
            out.append(char)
            index += 1
            continue

        if char in "{[":
            stack.append(char)
            expecting_key = char == "{"
            out.append(char)
            index += 1
            continue

        if char in "}]":
            if stack:
                stack.pop()
            expecting_key = False
            out.append(char)
            index += 1
            continue

        if char == ",":
            expecting_key = bool(stack) and stack[-1] == "{"
            out.append(char)
            index += 1
            continue

        if char == ":":
            expecting_key = False
            out.append(char)
            index += 1
            continue

        if char.isspace():
            out.append(char)
            index += 1
            continue

        if expecting_key and (char.isalpha() or char == "_"):
            end = index
            while end < len(raw) and (raw[end].isalnum() or raw[end] in "_-"):
                end += 1
            # Only a bare *key* — the identifier must be followed by a colon.
            after = end
            while after < len(raw) and raw[after].isspace():
                after += 1
            if after < len(raw) and raw[after] == ":":
                out.append('"' + raw[index:end] + '"')
                expecting_key = False
                index = end
                continue

        expecting_key = False
        out.append(char)
        index += 1

    return "".join(out)


def parse_json_object(raw: str):
    """Best-effort JSON-object extraction; falls back to slicing the first {...} span.

    The object counterpart of `parse_json_array`, and forgiving for the same reason:
    a model that wraps its answer in a sentence has still answered. The call
    analyser and the product-fit pass each carried their own copy of this regex
    before Stage 4; owning it here means they cannot drift on how a stray preamble
    is handled.
    """
    try:
        return parse_json(raw)
    except Exception:
        pass
    if "{" in raw and "}" in raw:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        span = raw[start:end]
        try:
            return json.loads(span)
        except Exception:
            pass
        # Last resort, and only ever reached once strict parsing has failed: a
        # single unquoted key must not cost a whole answer.
        try:
            return json.loads(_quote_bare_keys(span))
        except Exception:
            pass
    raise ValueError("could not parse JSON object from model output")
