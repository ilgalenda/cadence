from __future__ import annotations
"""Web Discovery capability service — find named people via web search.

The shared engine behind lead X-ray and high-intent detection. Both previously
duplicated the same steps: run a web_search research turn through the Mind, take
the terminal JSON array from the response, and normalise each row. They differ
only in their row schema (the ``normalise`` callback), how they read the text
(X-ray keeps the last block; detection joins all blocks), whether they surface an
incomplete stop, and what they do with the rows afterward — X-ray merges across
providers, ranks and groups; detection dedups and caps. Those differences stay
with the callers; this module owns the shared turn.

Discovery is public web search only — there is no LinkedIn API, and Lusha is not
used here (it is enrich-only; see :mod:`agents.services.enrichment`). Concurrency
governance stays with the caller (X-ray governs its provider loop; detection
governs its call), so this function takes no governor slot itself.
"""
from typing import Callable, Optional

from agents.mind import core as mind
from agents.shared.jsonparse import parse_json as _parse_json
from agents.shared.jsonparse import parse_json_array as _parse_json_array


def _terminal_text(message, mode: str) -> str:
    """Pull assistant text from a tool-using response.

    With web_search the model emits interim narration blocks between tool calls;
    only the terminal block holds the JSON array. ``mode='last'`` returns that
    final block; ``mode='join'`` concatenates every text block.
    """
    blocks = [
        (getattr(b, "text", "") or "").strip()
        for b in (getattr(message, "content", []) or [])
        if getattr(b, "type", None) == "text" and (getattr(b, "text", "") or "").strip()
    ]
    if not blocks:
        return ""
    return blocks[-1] if mode == "last" else "\n".join(blocks)


def _research_turn(
    *,
    system,
    user_message: str,
    tool_choice: dict,
    max_uses: int,
    model: Optional[str],
    max_tokens: Optional[int],
    max_rounds: int,
    text_extract: str,
    flag_incomplete: bool,
    web_search_type: Optional[str],
) -> tuple[str, Optional[str], Optional[str]]:
    """Run one web-search turn. Returns ``(raw_text, incomplete, fatal)``.

    ``fatal`` is set when the call itself failed and there is nothing to parse.
    ``incomplete`` is set when the turn ran but did not end cleanly — the text is
    still returned, because a truncated answer usually contains most of what was
    asked for and discarding it silently is worse than reporting it.

    Both callers below share this because *what a research turn does when it ends
    badly* is the part worth having in one place.
    """
    # Omitted rather than passed as None, so the Mind's own default stands.
    tool_generation = {"web_search_type": web_search_type} if web_search_type else {}
    try:
        result = mind.research(
            system=system,
            messages=[{"role": "user", "content": user_message}],
            tool_choice=tool_choice,
            max_uses=max_uses,
            model=model,
            max_tokens=max_tokens,
            max_rounds=max_rounds,
            **tool_generation,
        )
    except Exception as e:
        return "", None, f"api_error: {e}"

    raw_text = _terminal_text(result.message, text_extract)
    incomplete = None
    if flag_incomplete and getattr(result, "stop_reason", None) != "end_turn":
        incomplete = f"incomplete_response: {result.stop_reason}"
    return raw_text, incomplete, None


def search_people(
    *,
    system,
    user_message: str,
    normalise: Callable[[dict], Optional[dict]],
    tool_choice: dict,
    max_uses: int,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_rounds: int = 6,
    text_extract: str = "last",
    flag_incomplete: bool = True,
    web_search_type: Optional[str] = None,
) -> dict:
    """Run one web-search discovery turn and return normalised people rows.

    Returns ``{"results": [...], "raw": str, "error": str | None}``. ``normalise``
    maps a raw row to the caller's schema, or returns None to drop it. When
    ``flag_incomplete`` and the turn did not end cleanly, the incompleteness is
    surfaced in ``error`` while any rows already parsed are still returned.

    ``web_search_type`` overrides the tool generation; omit it for the Mind's
    default. Callers that mine raw snippets for names set it explicitly.
    """
    raw_text, incomplete, fatal = _research_turn(
        system=system,
        user_message=user_message,
        tool_choice=tool_choice,
        max_uses=max_uses,
        model=model,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
        text_extract=text_extract,
        flag_incomplete=flag_incomplete,
        web_search_type=web_search_type,
    )
    if fatal:
        return {"results": [], "raw": raw_text, "error": fatal}

    try:
        parsed = _parse_json_array(raw_text)
    except Exception as e:
        return {"results": [], "raw": raw_text, "error": incomplete or f"parse_failed: {e}"}
    if not isinstance(parsed, list):
        return {"results": [], "raw": raw_text, "error": incomplete or "not_an_array"}

    rows = [r for r in (normalise(x) for x in parsed) if r]
    return {"results": rows, "raw": raw_text, "error": incomplete}


def research_object(
    *,
    system,
    user_message: str,
    tool_choice: dict,
    max_uses: int,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_rounds: int = 6,
    text_extract: str = "last",
    flag_incomplete: bool = True,
    web_search_type: Optional[str] = None,
) -> dict:
    """Run one web-search turn that answers with a single JSON *object*.

    The sibling of :func:`search_people` for research that produces one document
    rather than a list of rows — a company-and-person brief, for instance. Returns
    ``{"result": dict, "raw": str, "error": str | None}``, with ``result`` an empty
    dict when nothing parseable came back.
    """
    raw_text, incomplete, fatal = _research_turn(
        system=system,
        user_message=user_message,
        tool_choice=tool_choice,
        max_uses=max_uses,
        model=model,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
        text_extract=text_extract,
        flag_incomplete=flag_incomplete,
        web_search_type=web_search_type,
    )
    if fatal:
        return {"result": {}, "raw": raw_text, "error": fatal}

    try:
        parsed = _parse_json(raw_text)
    except Exception as e:
        return {"result": {}, "raw": raw_text, "error": incomplete or f"parse_failed: {e}"}
    if not isinstance(parsed, dict):
        return {"result": {}, "raw": raw_text, "error": incomplete or "not_an_object"}

    return {"result": parsed, "raw": raw_text, "error": incomplete}


def dedup_by_linkedin_url(rows: list[dict]) -> list[dict]:
    """Keep the first row per non-empty ``linkedin_url``; URL-less rows all pass.

    Order-preserving, so when rows are concatenated in source-precedence order
    the earlier source wins a tie.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        key = (row.get("linkedin_url") or "").lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    return out
