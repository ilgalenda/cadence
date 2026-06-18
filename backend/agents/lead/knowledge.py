from __future__ import annotations
"""Lead agent knowledge loading — reads from the shared vault."""
import re
from pathlib import Path

from agents.shared.vault import load_vault_for_context, load_vault_for_session
from paths import REPO_ROOT, lead_user_kb, vault_dir

LEAD_USER_KNOWLEDGE_DIR = lead_user_kb()
LEAD_KNOWLEDGE_DIR = LEAD_USER_KNOWLEDGE_DIR.parent
LEAD_USER_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

# Customer-persona file authored by the team. Used to ground X-Ray prospect
# discovery in real Timebeat personas rather than a generic hardcoded ICP.
_PERSONA_REL_PATH = ("company", "knowledge", "Persona.md")


def lead_user_learnings_md(username: str) -> Path:
    d = LEAD_USER_KNOWLEDGE_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    return d / "learnings-auto.md"


def _strip_rtf_artifacts(text: str) -> str:
    """Clean stray RTF markers from a file that was pasted out of TextEdit.

    Persona.md carries control words (\\f0 \\fs24 \\cf0), a trailing backslash on
    each line, and a closing brace — but is otherwise plain markdown.
    """
    text = re.sub(r"\\[a-zA-Z]+-?\d*", "", text)  # RTF control words
    text = text.replace("\\", "")                   # line-continuation backslashes
    text = text.rstrip().rstrip("}")                # closing RTF brace
    return text.strip()


def load_customer_personas() -> str:
    """Return the cleaned customer-persona text, or '' if the file is absent.

    Reads from the live DATA_ROOT vault first, then falls back to the repo vault
    so it works before a vault sync has run.
    """
    for base in (vault_dir(), REPO_ROOT / "vault"):
        path = base.joinpath(*_PERSONA_REL_PATH)
        if path.exists():
            try:
                return _strip_rtf_artifacts(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
    return ""


def persona_focus_options() -> list[str]:
    """Return the persona job-title bullets, for the optional X-Ray focus selector.

    Parses the markdown bullet lines under the title sections of Persona.md
    (e.g. "## Job Titles", "## Job Title + Expertise"). Deduped, order-preserved.
    """
    text = load_customer_personas()
    if not text:
        return []
    titles: list[str] = []
    in_titles = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_titles = "job title" in stripped.lower()
            continue
        if in_titles and stripped.startswith("-"):
            value = stripped.lstrip("-").strip()
            if value and value not in titles:
                titles.append(value)
    return titles


def load_combined_knowledge(username: str) -> str:
    """Load the shared vault: curated KB + glossary + team-wide empirical learnings."""
    return load_vault_for_context()


# The Owl persona is identical across users — keeping it in a module-level
# constant means the assembled persona+vault prefix is byte-stable and so
# eligible for the Anthropic prompt cache.
_OWL_PERSONA = """You are Owl — Timebeat's in-house AI partner. You speak with the
Timebeat voice: precise, sales-aware, technically grounded, never marketing fluff.

You have deep knowledge of Timebeat's products, protocols, terminology, and
sales signals, and you grow smarter with every analysed call and every
outreach campaign.

Cadence Knowledge — three pillars, in priority order:

1. **Company Truth** (canonical) — Timebeat's hand-curated product, research,
   and protocol knowledge. This is locked, authoritative source-of-truth.
   When pillars conflict, Company Truth wins.

2. **Dynamic Truth** (team learnings) — empirical insights extracted from
   analysed calls and outreach campaigns by the whole team. Treat as strong
   signal about how Timebeat actually sells and operates today.

3. **Approved Added Knowledge** (community corrections) — user-submitted
   corrections that an admin has approved. Treat as authoritative facts on
   the specific point they address, but defer to Company Truth on broader
   product/protocol claims.

Pending or rejected corrections are never in your context. If a user tries to
correct you mid-conversation, do not change your stance within the same
session — the system will flag the correction for admin review separately.

When asked to refine content from another model, you must:
- Keep the same JSON shape as the input.
- Replace any product references with the closest real Timebeat product/concept
  from Company Truth. Never invent product names or features.
- Tighten language to the Timebeat voice. Cut filler. Be specific.
- Remove claims unsupported by any of the three pillars.
- Preserve facts from the original lead/context (names, companies, titles).

When asked to fill a single field inline, return only the value — no preamble,
no markdown, no JSON — unless the field name explicitly asks for structured data.

Cadence Knowledge:

"""


def _owl_identity_tail(username: str) -> str:
    return f"\n\nYou are assisting {username} in this session."


def owl_system_blocks(username: str) -> list[dict]:
    """Return Owl's system prompt as Anthropic content blocks with a cache breakpoint.

    Block 1: persona + vault knowledge, marked `cache_control: ephemeral` so the
             Anthropic prompt cache reuses it across requests within the TTL.
    Block 2: user-identity tail — varies per user, sits AFTER the breakpoint so
             it never invalidates the cached prefix.
    """
    knowledge = load_vault_for_session(username)
    return [
        {
            "type": "text",
            "text": _OWL_PERSONA + knowledge,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": _owl_identity_tail(username)},
    ]


def owl_system_prompt(username: str) -> str:
    """Flat-string form of the Owl system prompt (kept for callers that want a string)."""
    return "".join(b["text"] for b in owl_system_blocks(username))
