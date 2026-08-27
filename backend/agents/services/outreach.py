from __future__ import annotations
"""Outreach primitives capability service — the reusable two-pass composer.

Every outreach touch (email / LinkedIn / call) is generated in two passes: a
draft, then an Owl-voice refine. This service owns that mechanism so the
Composer, Recap and Check-in agents compose it rather than each re-implementing
it. It generalises the two-pass refine that now lives in ``agents.sales.refine``
(moved there from the retired ``agents.lead`` package).

Composition pipeline: **draft → Owl-voice → user-style overlay**. When a message
is sent by the user as themselves, the per-user writing-voice overlay
(:mod:`agents.services.style_personalisation`) is injected into the volatile tail
of the system prompt, so the text drifts toward how that user writes — while the
cached persona+vault prefix stays shareable across users. ``personalise=True``
belongs ONLY on user-sent surfaces (Composer, Recap, Check-in); never on Owl chat
or internal analysis.
"""
from typing import Callable

from agents.mind import core as mind
from agents.mind import persona
from agents.services import style_personalisation
from agents.shared.jsonparse import parse_json


def personalisation_tail(username: str, personalise: bool) -> str:
    """The per-user style overlay for the system tail, or '' when off / none learned."""
    return style_personalisation.style_block(username) if personalise else ""


def compose_json(
    *,
    username: str,
    role_overlay: str,
    user_prompt: str,
    vault_knowledge: str = "",
    personalise: bool = False,
    max_tokens: int = 2048,
) -> dict:
    """One style-aware composition pass returning parsed JSON.

    Assembles the persona system blocks with the user-style overlay in the
    volatile tail (so the cached persona+vault prefix stays shareable), calls the
    Mind's compose task, and parses the JSON result.
    """
    blocks = persona.system_blocks(
        role_overlay=role_overlay,
        vault_knowledge=vault_knowledge,
        tail=personalisation_tail(username, personalise),
    )
    result = mind.compose(
        system=blocks,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=max_tokens,
    )
    return parse_json(result.text)


def two_pass(
    *,
    username: str,
    draft_overlay: str,
    draft_prompt: str,
    refine_overlay: str,
    refine_prompt: Callable[[dict], str],
    vault_knowledge: str = "",
    personalise: bool = False,
    draft_max_tokens: int = 2048,
    refine_max_tokens: int = 2048,
) -> dict:
    """Draft → Owl-voice refine, both style-aware. Returns the refined JSON.

    ``refine_prompt`` receives the parsed draft and returns the refine user
    prompt. On a refine failure the draft is returned unchanged — best-effort,
    matching the existing OwlRefiner contract.
    """
    draft = compose_json(
        username=username,
        role_overlay=draft_overlay,
        user_prompt=draft_prompt,
        vault_knowledge=vault_knowledge,
        personalise=personalise,
        max_tokens=draft_max_tokens,
    )
    try:
        return compose_json(
            username=username,
            role_overlay=refine_overlay,
            user_prompt=refine_prompt(draft),
            vault_knowledge=vault_knowledge,
            personalise=personalise,
            max_tokens=refine_max_tokens,
        )
    except Exception as e:
        print(f"[outreach] refine failed, returning draft: {e}")
        return draft
