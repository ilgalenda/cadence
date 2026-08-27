from __future__ import annotations
"""OwlRefiner — the analysis pass-2 abstraction.

Moved from `agents/lead/owl.py`. Composition (Composer, Recap, Check-in) uses
`services.outreach.two_pass` instead; this remains the refine pass for *analysis*,
where the second pass corrects a structured reading rather than rewriting prose.

Today: Claude with the Acme KB persona.
Tomorrow: swap to a real Acme AI service. Same interface.
"""
import json

from agents.sales import prompts
from agents.mind.blocks import REFINE_OVERLAY, owl_system_blocks
from agents.mind import core as mind
from agents.shared.jsonparse import parse_json


class OwlRefiner:
    def __init__(self, username: str):
        self.username = username

    def _call(self, user_prompt: str, max_tokens: int = 2048) -> str:
        # Owl Core: one gateway, current model, centralised retry + usage logging.
        result = mind.compose(
            system=owl_system_blocks(self.username, role_overlay=REFINE_OVERLAY),
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=max_tokens,
        )
        return result.text


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
            elif task == "gtm_targets":
                user_prompt = prompts.owl_refine_gtm_targets_prompt(
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
        user_prompt = f"""Fill the field "{field}" for a Acme outreach campaign.

Current campaign state (read-only context):
{json.dumps(current_state, indent=2, default=str)}

User instruction: {instruction or '(no specific instruction — use the context to suggest the best value)'}

Return ONLY the value for the "{field}" field. No preamble, no markdown, no JSON wrapper."""
        return self._call(user_prompt, max_tokens=512)