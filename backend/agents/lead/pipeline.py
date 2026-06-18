from __future__ import annotations
"""Two-pass orchestration: Claude generation -> Owl refinement."""
import json
import os
import threading
import time

import anthropic

from agents.lead import knowledge, name_sources, prompts, scoring
from agents.lead.owl import OwlRefiner
from agents.shared.jsonparse import parse_json as _parse_json

_RETRY_DELAYS = [10, 30, 60]  # seconds between retries on 429

# One heavy pipeline operation at a time across all users, to keep concurrent
# token spend within the org TPM limit.
# KNOWN LIMITATION: this is a single global slot, so a long generate_xray
# (multiple sequential web_search rounds, ~30-60s) blocks every other user's
# unrelated signal/sequence calls (head-of-line blocking). Replacing it
# correctly needs a token-bucket limiter keyed on actual token spend, not a
# per-operation semaphore (more slots would blow the TPM ceiling) — tracked as
# separate work.
_PIPELINE_SEMAPHORE = threading.Semaphore(1)


def _claude_call(user_prompt: str, max_tokens: int, image_b64: str | None = None, image_media_type: str | None = None):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    if image_b64:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type or "image/png",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": user_prompt},
        ]
    else:
        content = user_prompt

    last_err = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=prompts.CLAUDE_BASE_SYSTEM,
                messages=[{"role": "user", "content": content}],
            )
            return response.content[0].text.strip()
        except anthropic.RateLimitError as e:
            last_err = e
            if attempt == len(_RETRY_DELAYS):
                raise
    raise last_err


def generate_signal(username: str, text: str | None, structured: dict | None, image_b64: str | None, image_media_type: str | None) -> dict:
    with _PIPELINE_SEMAPHORE:
        user_prompt = prompts.claude_signal_prompt(text, structured)
        raw = _claude_call(user_prompt, max_tokens=1024, image_b64=image_b64, image_media_type=image_media_type)
        claude_out = _parse_json(raw)

        lead_blob = json.dumps({"text": text, "structured": structured}, indent=2)
        refined = OwlRefiner(username).refine("signal", claude_out, {"lead_blob": lead_blob})
        owl_applied = refined != claude_out
        # Refinement may, in rare cases, return non-dict JSON; the score keys
        # below require a mutable dict, so fall back to the pass-1 output.
        if not isinstance(refined, dict):
            refined = claude_out if isinstance(claude_out, dict) else {}
            owl_applied = False

        # Deterministic behavioural score from Leadinfo page-visit data. Computed
        # here (not by the model) so it is reproducible and tunable. Attached to
        # the signal analysis under stable keys for the UI to surface.
        score = scoring.score_lead(text, structured, refined)
        refined["lead_score"] = score["score"]
        refined["lead_grade"] = score["grade"]
        refined["score_breakdown"] = score["breakdown"]
        refined["score_signals"] = score["signals"]

        return {
            "final": refined,
            "claude_raw": claude_out,
            "owl_applied": owl_applied,
        }


def generate_sequence_for_recipient(username: str, analysis: dict, config: dict, recipient: dict) -> dict:
    """Generate one personalised sequence for a single recipient."""
    user_prompt = prompts.claude_sequence_prompt(analysis, config, recipient=recipient)
    raw = _claude_call(user_prompt, max_tokens=4096)
    claude_out = _parse_json(raw)
    refined = OwlRefiner(username).refine(
        "sequence",
        claude_out,
        {"analysis": analysis, "config": {**config, "recipient": recipient}},
    )
    return {
        "final": refined,
        "claude_raw": claude_out,
        "owl_applied": refined != claude_out,
    }


def generate_sequences(username: str, analysis: dict, config: dict, recipients: list[dict]) -> dict:
    """Generate one personalised sequence per recipient.

    Returns:
      {
        "recipients": [{id, name, role, linkedin_url, sequence: [...]}],
        "owl_applied": bool   # true if any recipient was refined
      }
    """
    with _PIPELINE_SEMAPHORE:
        out_recipients = []
        any_owl = False
        for i, r in enumerate(recipients):
            if i > 0:
                time.sleep(5)  # spread calls to stay within TPM limits
            result = generate_sequence_for_recipient(username, analysis, config, r)
            touches = (result["final"] or {}).get("touches") or []
            out_recipients.append({
                "id": r.get("id"),
                "name": r.get("name", ""),
                "role": r.get("role", ""),
                "linkedin_url": r.get("linkedin_url", ""),
                "sequence": touches,
            })
            any_owl = any_owl or result["owl_applied"]
        return {"recipients": out_recipients, "owl_applied": any_owl}


def regenerate_touch(username: str, analysis: dict, config: dict, sequence: list[dict], n: int, recipient: dict | None = None) -> dict:
    with _PIPELINE_SEMAPHORE:
        user_prompt = prompts.claude_touch_regen_prompt(analysis, config, sequence, n, recipient=recipient)
        raw = _claude_call(user_prompt, max_tokens=1024)
        claude_out = _parse_json(raw)
        refined = OwlRefiner(username).refine(
            "touch_regenerate",
            claude_out,
            {"analysis": analysis, "config": config, "sequence": sequence, "touch": n, "recipient": recipient},
        )
        return {
            "final": refined,
            "claude_raw": claude_out,
            "owl_applied": refined != claude_out,
        }


def generate_boolean(username: str, analysis: dict, config: dict) -> dict:
    with _PIPELINE_SEMAPHORE:
        user_prompt = prompts.claude_boolean_prompt(analysis, config)
        raw = _claude_call(user_prompt, max_tokens=2048)
        claude_out = _parse_json(raw)
        refined = OwlRefiner(username).refine("boolean", claude_out, {"analysis": analysis, "config": config})
        return {
            "final": refined,
            "claude_raw": claude_out,
            "owl_applied": refined != claude_out,
        }


def generate_abm_identification(username: str, analysis: dict, config: dict) -> dict:
    with _PIPELINE_SEMAPHORE:
        user_prompt = prompts.claude_abm_identification_prompt(analysis, config)
        raw = _claude_call(user_prompt, max_tokens=2048)
        claude_out = _parse_json(raw)
        refined = OwlRefiner(username).refine(
            "abm_identification",
            claude_out,
            {"analysis": analysis, "config": config},
        )
        return {
            "final": refined,
            "claude_raw": claude_out,
            "owl_applied": refined != claude_out,
        }


def generate_xray(
    username: str,
    signal_final: dict | None,
    structured: dict | None,
    focus_personas: list[str] | None = None,
) -> dict:
    """Run X-Ray prospect discovery across every enabled name source.

    Each provider (web_search today; gtm.ai/ZoomInfo later) runs independently;
    their results are merged and deduped by LinkedIn URL. The search is grounded
    in the team's customer-persona file, optionally narrowed to ``focus_personas``.

    Returns: {results: [...], grouped: {linkedin_direct, email_enrichment, campaign_context}, raw, error}
    """
    payload = prompts.xray_user_payload(signal_final, structured)
    if not payload.get("company_name"):
        return {"results": [], "grouped": _empty_buckets(), "raw": "", "error": "missing_company"}

    personas = knowledge.load_customer_personas()
    system_prompt = prompts.xray_system_prompt(personas, focus_personas)
    user_message = prompts.xray_user_message(payload)

    sources = name_sources.enabled_sources()
    if not sources:
        return {"results": [], "grouped": _empty_buckets(), "raw": "", "error": "no_enabled_sources"}

    merged: list[dict] = []
    seen_urls: set[str] = set()
    raws: list[str] = []
    errors: list[str] = []

    with _PIPELINE_SEMAPHORE:
        for src in sources:
            out = src.discover(system_prompt, user_message)
            if out.get("raw"):
                raws.append(f"[{src.name}]\n{out['raw']}")
            if out.get("error"):
                errors.append(f"{src.name}: {out['error']}")
            for row in out.get("results", []):
                url_key = row["linkedin_url"].lower()
                if url_key and url_key in seen_urls:
                    continue
                if url_key:
                    seen_urls.add(url_key)
                merged.append(row)

    # Rank high → low intent, then cap. Path tier dominates (a confirmed LinkedIn
    # profile ready for outreach beats a context-only mention), confidence breaks ties.
    merged.sort(key=_xray_intent_score, reverse=True)
    merged = merged[:name_sources.XRAY_MAX_RESULTS]

    grouped = _empty_buckets()
    for row in merged:
        row["intent_score"] = _xray_intent_score(row)
        grouped[row["recommended_path"]].append(row)

    # Only surface an error when no source produced any usable result.
    error = None if merged else ("; ".join(errors) or "no_results")
    return {"results": merged, "grouped": grouped, "raw": "\n\n".join(raws), "error": error}


_XRAY_PATH_WEIGHT = {"linkedin_direct": 3, "email_enrichment": 2, "campaign_context": 1}
_XRAY_CONF_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def _xray_intent_score(row: dict) -> int:
    """Rank a prospect by outreach intent: path tier (×10) then confidence."""
    path = _XRAY_PATH_WEIGHT.get(row.get("recommended_path"), 1)
    conf = _XRAY_CONF_WEIGHT.get(row.get("confidence"), 1)
    return path * 10 + conf


def _empty_buckets() -> dict:
    return {"linkedin_direct": [], "email_enrichment": [], "campaign_context": []}


def generate_abm_sequence(username: str, analysis: dict, config: dict, contacts: list[dict]) -> dict:
    with _PIPELINE_SEMAPHORE:
        user_prompt = prompts.claude_abm_sequence_prompt(analysis, config, contacts)
        raw = _claude_call(user_prompt, max_tokens=6144)
        claude_out = _parse_json(raw)
        refined = OwlRefiner(username).refine(
            "abm_sequence",
            claude_out,
            {"analysis": analysis, "config": config, "contacts": contacts},
        )
        return {
            "final": refined,
            "claude_raw": claude_out,
            "owl_applied": refined != claude_out,
        }
