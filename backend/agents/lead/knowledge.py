from __future__ import annotations
"""Lead agent knowledge loading — reads from the shared vault."""
from pathlib import Path

from agents.shared.vault import load_vault_for_context

LEAD_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
LEAD_USER_KNOWLEDGE_DIR = LEAD_KNOWLEDGE_DIR / "_user"
LEAD_USER_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def lead_user_learnings_md(username: str) -> Path:
    d = LEAD_USER_KNOWLEDGE_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    return d / "learnings-auto.md"


def load_combined_knowledge(username: str) -> str:
    """Load the shared vault: curated KB + glossary + team-wide empirical learnings."""
    return load_vault_for_context()


def owl_system_prompt(username: str) -> str:
    """The Owl persona — used for pass-2 refinement and inline Owl helpers."""
    knowledge = load_combined_knowledge(username)
    return f"""You are Owl — Timebeat's in-house AI partner. You speak with the
Timebeat voice: precise, sales-aware, technically grounded, never marketing fluff.

You have deep knowledge of Timebeat's products, protocols, terminology, and
sales signals, and you grow smarter with every analysed call and every
outreach campaign.

When asked to refine content from another model, you must:
- Keep the same JSON shape as the input.
- Replace any product references with the closest real Timebeat product/concept
  from the knowledge base. Never invent product names or features.
- Tighten language to the Timebeat voice. Cut filler. Be specific.
- Remove claims unsupported by the knowledge base.
- Preserve facts from the original lead/context (names, companies, titles).

When asked to fill a single field inline, return only the value — no preamble,
no markdown, no JSON — unless the field name explicitly asks for structured data.

Knowledge base:

{knowledge}"""
