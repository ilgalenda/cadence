from __future__ import annotations
"""Two-pass orchestration: Claude generation -> Owl refinement."""
import json
import os
import threading
import time

import anthropic

from agents.lead import prompts
from agents.lead.owl import OwlRefiner

XRAY_MODEL = "claude-sonnet-4-6"
XRAY_MAX_RESULTS = 10

_RETRY_DELAYS = [10, 30, 60]  # seconds between retries on 429

# One heavy pipeline operation at a time across all users.
# Keeps concurrent token spend within the org TPM limit.
_PIPELINE_SEMAPHORE = threading.Semaphore(1)


def _parse_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    return json.loads(raw)


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
        return {
            "final": refined,
            "claude_raw": claude_out,
            "owl_applied": refined != claude_out,
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


def _extract_text_blocks(response) -> str:
    """Concatenate all text blocks from a tool-using assistant response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text.strip():
                parts.append(text)
    return "\n".join(parts).strip()


def _parse_json_array(raw: str):
    """Best-effort JSON-array extraction. Falls back to slicing the first [...] span."""
    try:
        return _parse_json(raw)
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


def _normalise_xray_row(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    full_name = (row.get("full_name") or "").strip()
    linkedin_url = (row.get("linkedin_url") or "").strip()
    match_reason = (row.get("match_reason") or "").strip()
    if not full_name or not match_reason:
        return None
    path = (row.get("recommended_path") or "").strip().lower()
    if path not in {"linkedin_direct", "email_enrichment", "campaign_context"}:
        path = "campaign_context"
    confidence = (row.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    return {
        "full_name": full_name,
        "job_title": (row.get("job_title") or "").strip(),
        "company": (row.get("company") or "").strip(),
        "linkedin_url": linkedin_url,
        "confidence": confidence,
        "recommended_path": path,
        "match_reason": match_reason,
        "source_query": (row.get("source_query") or "").strip(),
    }


def generate_xray(username: str, signal_final: dict | None, structured: dict | None) -> dict:
    """Run the X-Ray sub-agent: web_search-backed prospect discovery.

    Returns: {results: [...], grouped: {linkedin_direct, email_enrichment, campaign_context}, raw, error}
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"results": [], "grouped": _empty_buckets(), "raw": "", "error": "missing_api_key"}

    payload = prompts.xray_user_payload(signal_final, structured)
    if not payload.get("company_name"):
        return {"results": [], "grouped": _empty_buckets(), "raw": "", "error": "missing_company"}

    system_prompt = prompts.XRAY_SYSTEM_PROMPT

    with _PIPELINE_SEMAPHORE:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=XRAY_MODEL,
                max_tokens=4096,
                system=system_prompt,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 8,
                }],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": prompts.xray_user_message(payload)}],
            )
        except Exception as e:
            return {"results": [], "grouped": _empty_buckets(), "raw": "", "error": f"api_error: {e}"}

    raw_text = _extract_text_blocks(response)
    try:
        parsed = _parse_json_array(raw_text)
    except Exception as e:
        return {"results": [], "grouped": _empty_buckets(), "raw": raw_text, "error": f"parse_failed: {e}"}

    if not isinstance(parsed, list):
        return {"results": [], "grouped": _empty_buckets(), "raw": raw_text, "error": "not_an_array"}

    seen_urls: set[str] = set()
    cleaned: list[dict] = []
    for row in parsed:
        norm = _normalise_xray_row(row)
        if not norm:
            continue
        url_key = norm["linkedin_url"].lower()
        if url_key and url_key in seen_urls:
            continue
        if url_key:
            seen_urls.add(url_key)
        cleaned.append(norm)
        if len(cleaned) >= XRAY_MAX_RESULTS:
            break

    grouped = _empty_buckets()
    for row in cleaned:
        grouped[row["recommended_path"]].append(row)

    return {"results": cleaned, "grouped": grouped, "raw": raw_text, "error": None}


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
