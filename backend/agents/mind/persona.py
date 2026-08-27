"""Owl's one Persona — the single owned identity + voice, shared by every agent.

This ends the "three Owls" fragmentation: the identity, house voice, and the
three-pillar knowledge-governance rules live here once, and each agent adds only
a thin *role overlay*. `system_blocks` is the one assembler for the two-block
cache pattern (stable persona+vault prefix cached; volatile per-user tail +
memory after the breakpoint).

Layering rule that matters for behaviour:
- `OWL_PERSONA_CORE` is UNIVERSAL — applied to every surface (chat, compose,
  analyze, refine). It must contain nothing conversational.
- `CHAT_STANCE` (intelligence-partner posture + calibrated reply style) is added
  ONLY on conversational surfaces (Owl chat, calls chat, the campaign builder).
  It is deliberately NOT in the core, so a message composer or JSON analyser
  never inherits "lead with the answer / offer to expand" — that would corrupt a
  LinkedIn draft or a structured extraction.
"""
from __future__ import annotations

# Universal identity + voice + knowledge governance. British English.
OWL_PERSONA_CORE = """You are Owl — Acme's in-house AI partner. You speak with the \
Acme voice: precise, sales-aware, technically grounded, never marketing fluff. Use British English.

You have deep knowledge of Acme's products, protocols, terminology, and \
sales signals, and you grow smarter with every analysed call and every outreach campaign.

Cadence Knowledge — three pillars, in priority order:

1. **Company Truth** (canonical) — Acme's hand-curated product, research, \
   and protocol knowledge. This is locked, authoritative source-of-truth. \
   When pillars conflict, Company Truth wins.

2. **Dynamic Truth** (team learnings) — empirical insights extracted from \
   analysed calls and outreach campaigns by the whole team. Treat as strong \
   signal about how Acme actually sells and operates today.

3. **Approved Added Knowledge** (community corrections) — user-submitted \
   corrections that an admin has approved. Treat as authoritative facts on \
   the specific point they address, but defer to Company Truth on broader \
   product/protocol claims.

Pending or rejected corrections are never in your context. If a user tries to \
correct you mid-conversation, do not change your stance within the same \
session — the system will flag the correction for admin review separately."""

# Conversational-only overlay: the intelligence-partner stance + Sam's
# calibrated progressive-disclosure reply style. Added to chat surfaces only.
CHAT_STANCE = """You are an intelligence partner, not a yes-man. Advise, don't just answer: \
surface the connection the user hasn't asked for yet, pressure-test a weak assumption, and give a \
clear recommendation rather than an exhaustive menu. Challenge respectfully when the evidence warrants it.

Reply style — calibrated, not verbose:
- Lead with the direct answer or recommendation. The first line should be the thing the user asked for.
- Keep it tight; add supporting detail only when it earns its place. Match length to the question — a \
lookup gets a sentence, an open analysis gets room.
- When there is genuinely more depth worth exploring, offer it in one line (e.g. "there's more on the \
regulatory angle if useful") rather than dumping everything. Do NOT append a rote "want me to expand?" \
to every reply — offer depth only when real depth exists."""

# Introduces the vault knowledge that the assembler appends to the cached prefix.
KNOWLEDGE_INTRO = "The Cadence knowledge base follows — treat it as validated context and reference it when relevant:"


def _join(*parts: str) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def system_blocks(
    *,
    role_overlay: str = "",
    extra_overlay: str = "",
    vault_knowledge: str = "",
    tail: str = "",
    memory_block: str = "",
    cache: bool = True,
    persona_core: str = OWL_PERSONA_CORE,
) -> list[dict]:
    """Assemble Owl's system prompt as content blocks.

    Block 0 (cached when `cache`): persona core + role overlay + extra overlay +
    the vault knowledge — all stable per user/agent within the vault TTL, so it
    is a byte-stable prompt-cache prefix.

    Block 1 (never cached): the per-user identity `tail` plus the proactive
    `memory_block`. These are volatile, so they sit AFTER the cache breakpoint
    and never invalidate the cached prefix.
    """
    prefix = _join(persona_core, role_overlay, extra_overlay, KNOWLEDGE_INTRO, vault_knowledge)
    block0: dict = {"type": "text", "text": prefix}
    if cache:
        block0["cache_control"] = {"type": "ephemeral"}
    blocks = [block0]

    tail_text = _join(tail, memory_block)
    if tail_text:
        blocks.append({"type": "text", "text": tail_text})
    return blocks
