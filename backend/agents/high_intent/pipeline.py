from __future__ import annotations
"""High-Intent pipeline.

Detection:   Claude Opus 4.7 + web_search — finds high-intent prospects
Composition: Claude Sonnet 4.6 + Vault context — expert 3-touch LinkedIn sequence
"""
import json
import os
import time
import threading

import anthropic

from agents.high_intent import prompts
from agents.lead.knowledge import load_combined_knowledge
from agents.shared.vault import load_vault_for_session, log_cache_usage

DETECTION_MODEL = "claude-opus-4-7"
COMPOSE_MODEL = "claude-sonnet-4-6"
DETECTION_MAX_RESULTS = 15

_RETRY_DELAYS = [10, 30, 60]
_PIPELINE_SEMAPHORE = threading.Semaphore(1)


def _api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return key


def _parse_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    return json.loads(raw)


def _parse_json_array(raw: str):
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


def _extract_text_blocks(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text.strip():
                parts.append(text)
    return "\n".join(parts).strip()


def _normalise_signal_row(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    full_name = (row.get("full_name") or "").strip()
    signal_context = (row.get("signal_context") or "").strip()
    if not full_name or not signal_context:
        return None
    confidence = (row.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    return {
        "full_name": full_name,
        "job_title": (row.get("job_title") or "").strip(),
        "company": (row.get("company") or "").strip(),
        "linkedin_url": (row.get("linkedin_url") or "").strip(),
        "confidence": confidence,
        "signal_type": (row.get("signal_type") or "").strip(),
        "signal_context": signal_context,
        "signal_date": (row.get("signal_date") or "").strip(),
        "timebeat_fit_reason": (row.get("timebeat_fit_reason") or "").strip(),
        "recommended_product": (row.get("recommended_product") or "").strip(),
        "source_query": (row.get("source_query") or "").strip(),
    }


def run_signal_detection(username: str, signal_type: str, icp_config: dict) -> dict:
    """Use Opus 4.7 + web_search to detect high-intent prospects for a given signal type.

    Returns: {results: [...], raw: str, error: str|None}
    """
    api_key = _api_key()
    user_message = prompts.detection_user_message(signal_type, icp_config)

    with _PIPELINE_SEMAPHORE:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=DETECTION_MODEL,
                max_tokens=4096,
                system=prompts.DETECTION_SYSTEM_PROMPT,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 8,
                }],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:
            return {"results": [], "raw": "", "error": f"api_error: {e}"}

    raw_text = _extract_text_blocks(response)
    try:
        parsed = _parse_json_array(raw_text)
    except Exception as e:
        return {"results": [], "raw": raw_text, "error": f"parse_failed: {e}"}

    if not isinstance(parsed, list):
        return {"results": [], "raw": raw_text, "error": "not_an_array"}

    seen_urls: set[str] = set()
    cleaned: list[dict] = []
    for row in parsed:
        norm = _normalise_signal_row(row)
        if not norm:
            continue
        url_key = norm["linkedin_url"].lower()
        if url_key and url_key in seen_urls:
            continue
        if url_key:
            seen_urls.add(url_key)
        cleaned.append(norm)
        if len(cleaned) >= DETECTION_MAX_RESULTS:
            break

    return {"results": cleaned, "raw": raw_text, "error": None}


def compose_message_sequence(username: str, signal: dict) -> dict:
    """Use Sonnet 4.6 + Vault context to generate a 3-touch LinkedIn sequence.

    Returns: {touches: [...], error: str|None}
    """
    api_key = _api_key()
    knowledge = load_vault_for_session(username)
    system_prompt = prompts.COMPOSE_SYSTEM_PROMPT_TEMPLATE.format(knowledge=knowledge)
    system_blocks = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    user_message = prompts.compose_user_message(signal)

    last_err = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=COMPOSE_MODEL,
                max_tokens=2048,
                system=system_blocks,
                messages=[{"role": "user", "content": user_message}],
            )
            log_cache_usage("high_intent.compose", response.usage)
            raw = response.content[0].text.strip()
            parsed = _parse_json(raw)
            return {"touches": parsed.get("touches", []), "error": None}
        except anthropic.RateLimitError as e:
            last_err = e
            if attempt == len(_RETRY_DELAYS):
                return {"touches": [], "error": f"rate_limit: {e}"}
        except Exception as e:
            return {"touches": [], "error": f"compose_failed: {e}"}
    return {"touches": [], "error": f"rate_limit: {last_err}"}


def compose_followup(username: str, signal: dict, reply_text: str) -> str | None:
    """Generate a follow-up response to a prospect's reply using Sonnet 4.6."""
    api_key = _api_key()
    knowledge = load_vault_for_session(username)
    system_prompt = prompts.COMPOSE_SYSTEM_PROMPT_TEMPLATE.format(knowledge=knowledge)
    system_blocks = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    user_message = prompts.followup_user_message(signal, reply_text)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=COMPOSE_MODEL,
            max_tokens=512,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
        )
        log_cache_usage("high_intent.followup", response.usage)
        return response.content[0].text.strip()
    except Exception:
        return None
