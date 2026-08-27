"""Prompt library — public showcase build.

Cadence keeps every prompt in one module so they can be reviewed, diffed and
version-controlled as a body of work rather than scattered through agent code.

This is the redacted build of that module. The prompts for the three exemplar
agents are present in full; the rest keep their signatures and docstrings and
lose their bodies. Regenerate with tools/redact-prompts.py — do not hand-edit.
"""


from __future__ import annotations

import json

def newsletter_quiz_prompt(*, count: int, products: str, glossary: str) -> str:
    """
    Client-facing educational questions. The audience is outside the company.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("newsletter_quiz_prompt is withheld from the public build.")

def certification_quiz_prompt(
    *, count: int, products: str, glossary: str, scenarios: list[dict],
) -> str:
    """
    Internal certification, generalised from real calls.

    The scenarios are anonymised before they reach here — concepts, objections and
    signals only, never a company or a person. The prompt says so again anyway,
    because the caller's filtering and the model's instruction are two independent
    guards on the same rule.

    Withheld from the public showcase — the prompt library is proprietary. The signature and docstring above are the full contract this prompt satisfies; see docs/agents/ for what it is asked to produce.
    """
    raise NotImplementedError("certification_quiz_prompt is withheld from the public build.")

