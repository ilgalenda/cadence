from __future__ import annotations
"""Name-source providers for X-Ray prospect discovery.

Each provider independently surfaces named individuals at a target company and
returns normalised rows. The orchestrator ([pipeline.generate_xray]) runs every
*enabled* provider and merges + dedupes the results, so adding a second source
later is a drop-in — the two systems stay independent.

Providers today:
  * WebSearchNameSource — Claude + the web_search tool (always on).
  * ZoomInfoNameSource  — gtm.ai / ZoomInfo MCP. STUB, off by default. There is
    no zero-cost access (a paid ZoomInfo seat is required to authenticate even
    the free, no-credit search tools), so it stays disabled until a seat is
    evaluated. Integration path is documented on the class.
"""
import os

import anthropic

from agents.shared.jsonparse import parse_json_array as _parse_json_array

XRAY_MODEL = "claude-sonnet-4-6"
XRAY_MAX_RESULTS = 15
# Cap web_search rounds. Each round is a sequential model+search round-trip
# (~8-12s), so this is the dominant latency lever. Broad queries that surface
# several people at once let us fill up to 15 results without many rounds.
XRAY_MAX_USES = 5

_VALID_PATHS = {"linkedin_direct", "email_enrichment", "campaign_context"}


# ---------------------------------------------------------------------------
# Shared parsing / normalisation helpers
# ---------------------------------------------------------------------------

def _extract_text_blocks(response) -> str:
    """Return the final text block from a tool-using assistant response.

    With the web_search tool the model emits interim narration text blocks
    between tool calls; only the terminal text block holds the JSON array.
    """
    last = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = (getattr(block, "text", "") or "").strip()
            if text:
                last = text
    return last


def normalise_row(row: dict, source: str) -> dict | None:
    """Validate and normalise one discovered row. Tags it with its source."""
    if not isinstance(row, dict):
        return None
    full_name = (row.get("full_name") or "").strip()
    match_reason = (row.get("match_reason") or "").strip()
    if not full_name or not match_reason:
        return None
    path = (row.get("recommended_path") or "").strip().lower()
    if path not in _VALID_PATHS:
        path = "campaign_context"
    confidence = (row.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    return {
        "full_name": full_name,
        "job_title": (row.get("job_title") or "").strip(),
        "company": (row.get("company") or "").strip(),
        "linkedin_url": (row.get("linkedin_url") or "").strip(),
        "confidence": confidence,
        "recommended_path": path,
        "match_reason": match_reason,
        "source_query": (row.get("source_query") or "").strip(),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class WebSearchNameSource:
    """Discovery via Claude + the web_search tool."""

    name = "web_search"

    @property
    def enabled(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY"))

    def discover(self, system_prompt: str, user_message: str) -> dict:
        """Return {"results": [...], "raw": str, "error": str | None}."""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return {"results": [], "raw": "", "error": "missing_api_key"}
        client = anthropic.Anthropic(api_key=api_key)
        messages = [{"role": "user", "content": user_message}]
        response = None
        # Long web_search turns return stop_reason="pause_turn"; we must feed the
        # partial turn back to let the model continue, or we lose all results.
        try:
            for _ in range(6):
                response = client.messages.create(
                    model=XRAY_MODEL,
                    max_tokens=8192,
                    system=system_prompt,
                    tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": XRAY_MAX_USES}],
                    tool_choice={"type": "auto"},
                    messages=messages,
                )
                if getattr(response, "stop_reason", None) != "pause_turn":
                    break
                messages.append({"role": "assistant", "content": response.content})
        except Exception as e:
            return {"results": [], "raw": "", "error": f"api_error: {e}"}

        raw_text = _extract_text_blocks(response)
        stop_reason = getattr(response, "stop_reason", None)
        # Even when the turn didn't finish cleanly (e.g. pause_turn loop
        # exhausted), try to salvage whatever candidates were already gathered
        # rather than discarding the whole search. The incompleteness is still
        # surfaced via the error field.
        incomplete = None if stop_reason == "end_turn" else f"incomplete_response: {stop_reason}"
        try:
            parsed = _parse_json_array(raw_text)
        except Exception as e:
            return {"results": [], "raw": raw_text, "error": incomplete or f"parse_failed: {e}"}
        if not isinstance(parsed, list):
            return {"results": [], "raw": raw_text, "error": incomplete or "not_an_array"}

        rows = [r for r in (normalise_row(x, self.name) for x in parsed) if r]
        return {"results": rows, "raw": raw_text, "error": incomplete}


class ZoomInfoNameSource:
    """gtm.ai / ZoomInfo MCP discovery — STUB, disabled by default.

    Integration path when a ZoomInfo seat is available:
      * Endpoint: https://mcp.zoominfo.com/mcp (OAuth via a ZoomInfo login).
      * Use the Anthropic Messages API remote-MCP connector, restricting tools to
        the free, no-credit search tools (search_contacts, search_companies,
        find_similar_contacts) — never the credit-consuming enrich_* tools.
      * Map each contact to the normalise_row() shape, source="zoominfo".
    Enable by setting GTMAI_ENABLED=true once auth is configured.
    """

    name = "zoominfo"

    @property
    def enabled(self) -> bool:
        return os.getenv("GTMAI_ENABLED", "false").strip().lower() in {"1", "true", "yes"}

    def discover(self, system_prompt: str, user_message: str) -> dict:
        # Not yet wired — requires a ZoomInfo seat + MCP auth. Returns nothing so
        # the orchestrator simply relies on the other enabled sources.
        return {"results": [], "raw": "", "error": "zoominfo_not_configured"}


# Registry. Order is the merge precedence (earlier sources win on dedupe ties).
ALL_SOURCES = [WebSearchNameSource(), ZoomInfoNameSource()]


def enabled_sources() -> list:
    return [s for s in ALL_SOURCES if s.enabled]
