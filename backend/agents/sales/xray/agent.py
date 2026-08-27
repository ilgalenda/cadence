"""X-ray — given an account and why it matters, find the people.

**One question, and the "why" is half of it.** Discovery reasons from the
grounding it is given: the vertical, the product line in play, the role already
seen. Hand it a bare company name and it has to guess all three, which is why a
name typed by hand has always been the weakest search this agent does.

So there is one mechanism and three ways to acquire the grounding, strongest
first:

- **a scored lead** — handed over from Lead scoring, or dropped straight onto
  X-ray, which scores it inline through `scoring.analyse` and carries on. The
  primary source (Sam, 2026-08-24).
- **a GTM target** — arriving with the vertical and the reason the company is on
  the list.
- **a bare company** — where `derive_grounding` classifies the account first, so
  discovery still reasons from a vertical and a product fit rather than a name.

**Sweeping for a signal is no longer here.** "Who, anywhere, is showing this
signal" has no account and therefore no grounding, which is exactly why it alone
had no ranking and no eval arm. It moved to `sales.signals`, where a signal is
already the subject.

No LinkedIn API is involved: this searches the public web for profiles that
search engines have already indexed. Enrichment (email, and phone only when
explicitly asked) is a separate step on the selected shortlist, so credit is
spent on people a human chose.
"""
from __future__ import annotations

from agents.mind import governor as mind_governor
from agents.sales import prompts
from agents.sales.xray import ranking
from agents.services import name_sources, web_discovery

#: Enough for the grounding object and its one-sentence note. The classify
#: profile budgets 400, which this can exceed — and a truncated JSON is a lost
#: grounding, which silently returns the search to guessing.
GROUNDING_MAX_TOKENS = 600


def _empty_buckets() -> dict:
    return {"linkedin_direct": [], "email_enrichment": [], "campaign_context": []}


# ── Mode 1: company-scoped ──────────────────────────────────────────────────

def shortlist(
    username: str,
    signal_final: dict | None,
    structured: dict | None,
    focus_personas: list[str] | None = None,
) -> dict:
    """A ranked shortlist of high ICP-match people at one company.

    Every enabled discovery provider runs independently and their results are
    merged and deduped by profile URL, so adding a provider later widens the net
    without changing this contract.

    Returns ``{results, grouped, raw, error, provider_errors, truncated,
    persona_source}``. The last three exist so a degraded run cannot pass for a
    clean one: `error` still means *nothing usable came back*, while
    `provider_errors` and `truncated` describe a run that returned something and
    still went wrong, and `persona_source` says which persona file shaped it.
    """
    payload = prompts.xray_user_payload(signal_final, structured)
    if not payload.get("company_name"):
        return _nothing("missing_company")

    personas, persona_source = _load_personas()
    system_prompt = prompts.xray_system_prompt(personas, focus_personas)
    user_message = prompts.xray_user_message(payload)

    sources = name_sources.enabled_sources()
    if not sources:
        return _nothing("no_enabled_sources", persona_source)

    merged: list[dict] = []
    seen: set[str] = set()
    raws: list[str] = []
    errors: list[str] = []
    truncated = False

    with mind_governor.slot():
        for source in sources:
            out = source.discover(system_prompt, user_message)
            if out.get("raw"):
                raws.append(f"[{source.name}]\n{out['raw']}")
            if out.get("error"):
                errors.append(f"{source.name}: {out['error']}")
                # A turn cut short still returns the rows gathered before the cut.
                # That is worth keeping, but it is not a complete answer, and the
                # caller has no way to tell the two apart unless we say so.
                if "incomplete_response" in str(out["error"]):
                    truncated = True
            for row in out.get("results", []):
                key = row["linkedin_url"].lower()
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                merged.append(row)

    # Ranked before the cap, so the cap keeps the best fifteen rather than the
    # first fifteen a provider happened to emit.
    merged = ranking.rank(merged)[:name_sources.XRAY_MAX_RESULTS]

    grouped = _empty_buckets()
    for row in merged:
        grouped[row["recommended_path"]].append(row)

    # `error` keeps its narrow meaning — *nothing usable came back* — because
    # routes and the eval's error-rate floor are both written against it.
    #
    # What used to happen next was the defect: every provider error was dropped
    # on the floor the moment a single row survived, so a half-failed run and a
    # clean one were indistinguishable. They travel separately now, and the
    # caller decides what to say about them.
    error = None if merged else ("; ".join(errors) or "no_results")
    return {
        "results": merged,
        "grouped": grouped,
        "raw": "\n\n".join(raws),
        "error": error,
        "provider_errors": errors,
        "truncated": truncated,
        "persona_source": persona_source,
    }


def _nothing(error: str, persona_source: str = "missing") -> dict:
    """An empty shortlist that still answers every question the contract asks."""
    return {
        "results": [],
        "grouped": _empty_buckets(),
        "raw": "",
        "error": error,
        "provider_errors": [],
        "truncated": False,
        "persona_source": persona_source,
    }


def _load_personas() -> tuple[str, str]:
    """The persona text, and which file it came from.

    The provenance matters because the fallback is silent: with no Persona.md
    the search still runs, on the prompt's own generic ICP, and nothing anywhere
    said so. A shortlist built on the generic list is a different shortlist.
    """
    from agents.mind import blocks

    return blocks.load_customer_personas_with_source()


# ── Acquiring the grounding ─────────────────────────────────────────────────

def from_lead(username: str, *, text: str, personas: list[str] | None = None) -> dict:
    """Score a lead that was dropped straight onto X-ray, then find the people.

    The same logic Lead scoring runs, composed rather than copied: `scoring.analyse`
    reads the blob and returns the verdict, and that verdict is the grounding the
    search then uses. Arriving from Lead scoring and pasting the lead here reach
    discovery by the same road; the only difference is who pressed the button.

    Returns the shortlist with the verdict attached as ``lead``, so the caller can
    show what the search was grounded in without scoring it a second time.
    """
    from agents.sales.scoring import agent as scoring

    blob = (text or "").strip()
    if not blob:
        return _nothing("missing_lead")

    verdict = scoring.analyse(username, text=blob).get("final") or {}
    if not (verdict.get("company") or "").strip():
        # A lead with no company cannot be searched, and saying so beats searching
        # for nobody. The verdict still goes back, because it is worth reading.
        out = _nothing("lead_has_no_company")
        out["lead"] = verdict
        return out

    out = shortlist(username, verdict, None, personas)
    out["lead"] = verdict
    return out


def derive_grounding(username: str, company: str) -> dict:
    """What a bare company name does not tell you, worked out before searching.

    Discovery reasons from a vertical and a product line to decide which technical
    function would own timing at an account. A scored lead supplies both; a typed
    name supplies neither, and the model was left inferring them silently inside
    the same call that was also meant to be finding people.

    So they are inferred *first*, cheaply and visibly, and handed in as grounding —
    which makes a company search the same shape as a lead search rather than a
    degraded one. Haiku, because this is classification, not judgement.

    Returns ``{industry, product_fit, note}``; empty strings when it cannot tell,
    which leaves the prompt exactly as bare as it used to be rather than inventing
    a vertical to fill the gap.
    """
    from agents.mind import core as mind
    from agents.shared.jsonparse import parse_json

    try:
        with mind_governor.slot():
            raw = mind.classify(
                system=prompts.GROUNDING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompts.grounding_user_message(company)}],
                # The classify profile budgets 400, which this object can exceed
                # once the note is written; a truncated JSON is a lost grounding.
                max_tokens=GROUNDING_MAX_TOKENS,
            ).text
        parsed = parse_json(raw)
    except Exception:  # noqa: BLE001
        # Grounding is an improvement on the search, never a precondition for it.
        # A failure here must cost accuracy, not the result.
        return {"industry": "", "product_fit": "", "note": ""}

    if not isinstance(parsed, dict):
        return {"industry": "", "product_fit": "", "note": ""}
    return {
        "industry": str(parsed.get("industry") or "").strip(),
        "product_fit": str(parsed.get("product_fit") or "").strip(),
        "note": str(parsed.get("note") or "").strip(),
    }


def from_company(
    username: str,
    company: str,
    personas: list[str] | None = None,
    *,
    ground: bool = True,
    grounding: dict | None = None,
) -> dict:
    """Find people at a company named by hand, grounding the search first.

    `grounding` is a correction made by hand: given, it is used as-is and the
    classification pass is skipped, because a person who has fixed the vertical
    should not be overruled by the model on the next run.

    `ground=False` skips the pass without supplying a replacement — used by the
    eval, so a measured change to discovery is not confounded by a second model
    call moving underneath it.
    """
    company = (company or "").strip()
    if not company:
        return _nothing("missing_company")

    blank = {"industry": "", "product_fit": "", "note": ""}
    if grounding is not None:
        grounding = {**blank, **grounding}
    elif ground:
        grounding = derive_grounding(username, company)
    else:
        grounding = blank
    structured = {"company": company}
    if grounding["industry"]:
        structured["industry"] = grounding["industry"]

    signal_final = {"company": company}
    if grounding["product_fit"]:
        signal_final["product_fit"] = grounding["product_fit"]

    out = shortlist(username, signal_final, structured, personas)
    out["grounding"] = grounding
    return out


# ── As a tool Owl can run ───────────────────────────────────────────────────

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {
            "type": "string",
            "description": "The company to find people at.",
        },
        "personas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional. Narrow to these target personas, e.g. 'Head of Infrastructure'.",
        },
    },
    "required": ["company"],
}


def run_as_tool(username: str, args: dict) -> str:
    """Run X-ray from conversation.

    Read-only: it finds people and reports them. It does not enrich — that spends
    Lusha credit and happens on the shortlist a human selected.
    """
    company = (args.get("company") or "").strip()
    if not company:
        # Sweeping for a signal moved to Signals, so the honest answer names
        # where that question now lives rather than failing silently.
        return (
            "Name a company to find people at. To sweep for people showing a "
            "buying signal instead, ask Signals."
        )

    out = from_company(username, company, args.get("personas"))
    people = out["results"]
    where = f"at {company}"

    if out.get("error") and not people:
        return f"X-ray found nothing {where} ({out['error']})."
    if not people:
        return f"X-ray found nobody {where}."

    def describe(person: dict) -> str:
        parts = [person.get("full_name") or person.get("name") or "?"]
        if person.get("job_title"):
            parts.append(person["job_title"])
        # The company is redundant when every result is from the one we searched.
        if person.get("company") and not company:
            parts.append(person["company"])
        return "- " + " · ".join(parts)

    lines = [describe(p) for p in people[:10]]
    more = f"\n…and {len(people) - 10} more." if len(people) > 10 else ""

    # An answer in conversation carries no error field for anyone to inspect, so
    # a run that half-failed has to say so in the prose or it will not be said
    # at all — this is the reply where a silently partial result does most harm.
    caveats = []
    if out.get("truncated"):
        caveats.append("the model's answer was cut short, so this list may be incomplete")
    for note in out.get("provider_errors") or []:
        if "incomplete_response" not in str(note):
            caveats.append(str(note))
    warning = f"\n\nWorth knowing: {'; '.join(caveats)}." if caveats else ""

    return (
        f"{len(people)} people {where}:\n" + "\n".join(lines) + more + warning
        + "\n\nThe shortlist is on the X-ray page. Select who to enrich — emails come back "
        "automatically, phone numbers only when you ask."
    )
