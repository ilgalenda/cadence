from __future__ import annotations
"""Lead agent knowledge loading — reads from the shared vault."""
import logging
import re
from pathlib import Path

from agents.mind import persona
from agents.shared.vault import load_vault_for_context, load_vault_for_session
from paths import REPO_ROOT, sales_user_kb, vault_dir

log = logging.getLogger(__name__)

USER_KNOWLEDGE_DIR = sales_user_kb()
KNOWLEDGE_DIR = USER_KNOWLEDGE_DIR.parent
USER_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

# Customer-persona file authored by the team. Used to ground X-Ray prospect
# discovery in real Acme personas rather than a generic hardcoded ICP.
_PERSONA_REL_PATH = ("company", "knowledge", "Persona.md")


def lead_user_learnings_md(username: str) -> Path:
    d = USER_KNOWLEDGE_DIR / username
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


def load_customer_personas_with_source() -> tuple[str, str]:
    """The cleaned persona text, and which file produced it.

    Reads from the live DATA_ROOT vault first, then falls back to the repo vault
    so it works before a vault sync has run. Source is ``data_root``, ``repo`` or
    ``missing``.

    The provenance is returned rather than inferred because both failures here
    are silent ones. With no file at all, X-Ray runs on the prompt's own generic
    ICP and produces a plausible, differently-targeted shortlist; with an
    unreadable file, it quietly falls through to the repo copy, which may be
    older than the one the team edits. Neither is visible in the results.
    """
    for base, name in ((vault_dir(), "data_root"), (REPO_ROOT / "vault", "repo")):
        path = base.joinpath(*_PERSONA_REL_PATH)
        if path.exists():
            try:
                return _strip_rtf_artifacts(path.read_text(encoding="utf-8", errors="replace")), name
            except Exception:
                log.warning("persona file at %s could not be read; falling through", path, exc_info=True)
                continue
    return "", "missing"


def load_customer_personas() -> str:
    """The persona text alone, for callers that cannot act on the provenance."""
    return load_customer_personas_with_source()[0]


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


# Lead-agent role overlay: the refine/fill task rules (formerly smuggled inside
# the persona constant). These are task instructions, not identity — the shared
# identity now lives once in agents/mind/persona.py.
REFINE_OVERLAY = """When asked to refine content from another model, you must:
- Keep the same JSON shape as the input.
- Replace any product references with the closest real Acme product/concept
  from Company Truth. Never invent product names or features.
- Tighten language to the Acme voice. Cut filler. Be specific.
- Remove claims unsupported by any of the three pillars.
- Preserve facts from the original lead/context (names, companies, titles).

When asked to fill a single field inline, return only the value — no preamble,
no markdown, no JSON — unless the field name explicitly asks for structured data."""


def owl_identity_tail(username: str) -> str:
    return f"You are assisting {username} in this session."


def owl_system_blocks(
    username: str,
    *,
    role_overlay: str = "",
    extra_overlay: str = "",
    memory_block: str = "",
    project_block: str = "",
    contributions_block: str = "",
) -> list[dict]:
    """Owl's system blocks: the shared persona + a per-agent `role_overlay` +
    the session vault (cached prefix), then the per-user identity tail, the
    proactive `memory_block`, and any `project_block` (all uncached). Delegates
    to agents/mind/persona so the identity is owned in exactly one place.

    `project_block` carries an Owl project's standing instructions. It rides the
    uncached tail alongside memory, deliberately: instructions differ per project
    but the persona+vault prefix must stay byte-stable so the prompt cache is
    shared across every project and user.

    `contributions_block` names which of the shared vault this user contributed,
    and rides the tail for exactly the same reason. It changes presentation only:
    the knowledge itself is in the cached prefix for everybody, contributor or
    not. See `agents/mind/contributions_block.py`.
    """
    tail_extras = "\n\n".join(
        p for p in (memory_block, project_block, contributions_block) if p and p.strip()
    )
    return persona.system_blocks(
        role_overlay=role_overlay,
        extra_overlay=extra_overlay,
        vault_knowledge=load_vault_for_session(username),
        tail=owl_identity_tail(username),
        memory_block=tail_extras,
        cache=True,
    )


def owl_system_prompt(username: str) -> str:
    """Flat-string form of the Owl system prompt (kept for callers that want a string)."""
    return "\n\n".join(b["text"] for b in owl_system_blocks(username))
