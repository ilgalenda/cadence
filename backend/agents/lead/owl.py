from __future__ import annotations
"""OwlRefiner — pass-2 abstraction.

Today: Claude with the Timebeat KB persona.
Tomorrow: swap to a real Timebeat AI service. Same interface.
"""
import json
import os
import time

import anthropic

from agents.lead import prompts
from agents.lead.knowledge import owl_system_blocks
from agents.shared.jsonparse import parse_json
from agents.shared.vault import log_cache_usage

_RETRY_DELAYS = [10, 30, 60]


class OwlRefiner:
    MODEL = "claude-sonnet-4-6"

    def __init__(self, username: str):
        self.username = username
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

    def _call(self, user_prompt: str, max_tokens: int = 2048) -> str:
        if not self._client:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        last_err = None
        for attempt, delay in enumerate([0] + _RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            try:
                response = self._client.messages.create(
                    model=self.MODEL,
                    max_tokens=max_tokens,
                    system=owl_system_blocks(self.username),
                    messages=[{"role": "user", "content": user_prompt}],
                )
                log_cache_usage("lead.owl_refiner", response.usage)
                return response.content[0].text.strip()
            except anthropic.RateLimitError as e:
                last_err = e
                if attempt == len(_RETRY_DELAYS):
                    raise
        raise last_err


    def refine(self, task: str, claude_output: dict, context: dict) -> dict:
        """Refine pass-1 output. On failure, return the input unchanged."""
        try:
            if task == "signal":
                user_prompt = prompts.owl_refine_signal_prompt(
                    claude_output, context.get("lead_blob", "")
                )
            elif task == "sequence":
                user_prompt = prompts.owl_refine_sequence_prompt(
                    claude_output, context["analysis"], context["config"]
                )
            elif task == "touch_regenerate":
                user_prompt = prompts.owl_refine_touch_prompt(
                    claude_output,
                    context["analysis"],
                    context["config"],
                    context.get("sequence", []),
                    context["touch"],
                )
            elif task == "boolean":
                user_prompt = prompts.owl_refine_boolean_prompt(
                    claude_output, context["analysis"], context["config"]
                )
            elif task == "abm_identification":
                user_prompt = prompts.owl_refine_abm_identification_prompt(
                    claude_output, context["analysis"], context["config"]
                )
            elif task == "abm_sequence":
                user_prompt = prompts.owl_refine_abm_sequence_prompt(
                    claude_output,
                    context["analysis"],
                    context["config"],
                    context.get("contacts", []),
                )
            else:
                return claude_output

            max_tokens = 4096 if task in ("sequence", "abm_sequence") else 2048
            raw = self._call(user_prompt, max_tokens=max_tokens)
            return parse_json(raw)
        except Exception as e:
            print(f"[lead.owl] refinement failed for task={task}: {e}")
            return claude_output

    def fill(self, field: str, current_state: dict, instruction: str) -> str:
        """Inline 'Ask Owl to fill this' helper. Returns a plain string value."""
        user_prompt = f"""Fill the field "{field}" for a Timebeat outreach campaign.

Current campaign state (read-only context):
{json.dumps(current_state, indent=2, default=str)}

User instruction: {instruction or '(no specific instruction — use the context to suggest the best value)'}

Return ONLY the value for the "{field}" field. No preamble, no markdown, no JSON wrapper."""
        return self._call(user_prompt, max_tokens=512)