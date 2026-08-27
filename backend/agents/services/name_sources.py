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
import re

from agents.services import web_discovery

# The cited web_search generation wraps quoted spans in `<cite index="4-1">…</cite>`
# inside the very strings we display. The citation is presentation markup, not
# part of the sentence, so it is stripped on the way in rather than escaped on
# the way out — a match_reason is read by a human, not rendered as HTML.
_CITE_TAG = re.compile(r"</?cite\b[^>]*>")


def _plain(value: object) -> str:
    """One model-authored string, stripped of citation markup and whitespace."""
    return _CITE_TAG.sub("", str(value or "")).strip()


def _bare_domain(value: object) -> str:
    """A company domain reduced to host form, e.g. ``northgate.com``.

    Carried because it is the strongest key the enrichment provider matches on —
    a name alone is ambiguous across subsidiaries. Asked for as a bare domain but
    normalised anyway, since a model told "no scheme or path" still sometimes
    supplies one, and a `https://` prefix would simply fail to match.
    """
    text = _plain(value).lower()
    if not text:
        return ""
    text = text.split("://", 1)[-1]        # drop any scheme
    text = text.split("/", 1)[0]           # drop any path
    text = text.removeprefix("www.").strip(" .")
    # A domain with no dot is not a domain; better empty than a bad match key.
    return text if "." in text else ""

XRAY_MAX_RESULTS = 15
# Cap web_search rounds. Each round is a sequential model+search round-trip
# (~8-12s), so this is the dominant latency lever. Broad queries that surface
# several people at once let us fill up to 15 results without many rounds.
XRAY_MAX_USES = 5

# Discovery pins the pre-dynamic-filtering web_search generation, deliberately.
# The current default (`web_search_20260209`) filters results through server-side
# code execution before the model sees them, and those internal steps draw down
# the same `max_uses` budget as real queries. That is the right trade for research
# that wants a digest; it is the wrong one here, because X-ray's whole job is
# reading names and titles out of raw result snippets. Measured on one company,
# same prompt and model: 15 people on `20250305` against 2 on `20260209`, which
# spent most of its budget filtering rather than searching.
XRAY_WEB_SEARCH_TYPE = "web_search_20250305"

# Room for 15 rows that each carry a two-sentence, KB-grounded match_reason.
# A full array measured ~4.7k output tokens, and a truncated one is not a short
# answer but an unparseable one — the array never closes.
XRAY_MAX_TOKENS = 16384

_VALID_PATHS = {"linkedin_direct", "email_enrichment", "campaign_context"}


# ---------------------------------------------------------------------------
# Shared parsing / normalisation helpers
# ---------------------------------------------------------------------------

def normalise_row(row: dict, source: str) -> dict | None:
    """Validate and normalise one discovered row. Tags it with its source."""
    if not isinstance(row, dict):
        return None
    full_name = _plain(row.get("full_name"))
    match_reason = _plain(row.get("match_reason"))
    if not full_name or not match_reason:
        return None
    path = _plain(row.get("recommended_path")).lower()
    if path not in _VALID_PATHS:
        path = "campaign_context"
    confidence = _plain(row.get("confidence")).lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    return {
        "full_name": full_name,
        "job_title": _plain(row.get("job_title")),
        "company": _plain(row.get("company")),
        "company_domain": _bare_domain(row.get("company_domain")),
        "linkedin_url": _plain(row.get("linkedin_url")),
        "confidence": confidence,
        "recommended_path": path,
        "match_reason": match_reason,
        "source_query": _plain(row.get("source_query")),
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
        if not os.getenv("ANTHROPIC_API_KEY"):
            return {"results": [], "raw": "", "error": "missing_api_key"}
        # The shared Web Discovery turn: one web_search research call through the
        # Mind, terminal JSON array parsed and normalised. Incompleteness (a
        # pause_turn loop that ran out) is salvaged, not discarded.
        return web_discovery.search_people(
            system=system_prompt,
            user_message=user_message,
            normalise=lambda row: normalise_row(row, self.name),
            tool_choice={"type": "auto"},
            max_uses=XRAY_MAX_USES,
            max_tokens=XRAY_MAX_TOKENS,
            max_rounds=6,
            # Joined, not just the last block: with citations the terminal answer
            # arrives split across one text block per cited span, so the JSON
            # array's opening bracket and its closing one land in different
            # blocks. Taking the last block alone yields a mid-array fragment
            # that cannot parse; joining reassembles it, and the array extractor
            # ignores the narration either side.
            text_extract="join",
            flag_incomplete=True,
            web_search_type=XRAY_WEB_SEARCH_TYPE,
        )


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
