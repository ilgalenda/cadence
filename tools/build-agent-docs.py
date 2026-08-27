#!/usr/bin/env python3
"""Generate docs/agents/*.md for the eleven sales agents.

Each agent module already carries a long docstring explaining what it does and
why it is shaped that way — the reasoning was written next to the code, which is
where it stays true. Rather than restate it in a doc page that immediately drifts,
this lifts the docstring and frames it with the facts a reader wants first:
whether the agent's prompts are in this build, which Mind profile it calls,
whether a human gate sits in front of it, and where its routes live.

    tools/build-agent-docs.py
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SALES = ROOT / "backend" / "agents" / "sales"
OUT = ROOT / "docs" / "agents"

# module, title, route prefix, Mind profile, human gate, prompts in this build
AGENTS = [
    ("scoring", "Lead Scoring", "/api/sales/leads", "analyze", "none — a reading", True),
    ("gtm", "GTM", "/api/sales/gtm", "analyze", "the user selects targets", True),
    ("xray", "X-ray", "/api/sales/xray", "classify", "the user selects people to reveal", True),
    ("research", "Research", "/api/sales/research", "research", "none — internal preparation", False),
    ("campaign_intelligence", "Campaign Intelligence", "/api/sales/intel", "classify + analyze", "none — preparation", False),
    ("campaign_selection", "Campaign Selection", "/api/sales/campaign", "none — deterministic", "the selection is the gate", False),
    ("composer", "Composer", "/api/sales/composer", "compose", "review queue, then a Gmail draft", False),
    ("call_analysis", "Call Analysis", "/api/sales/calls", "analyze", "none — a reading", False),
    ("recap", "Recap", "/api/sales/recap", "compose", "review queue, then a Gmail draft", False),
    ("knowledge_capture", "Knowledge Capture", "— surfaceless", "analyze", "staging automatic; promotion curated", False),
    ("signals", "Signals", "/api/sales/signals", "research", "none — a monitor", False),
]

FULL = (
    "**Prompts: in this build.** This is one of the three exemplar agents, published "
    "with its prompts intact so the prompt engineering is readable, not just described."
)
WITHHELD = (
    "**Prompts: withheld.** The module ships with its signatures and docstrings; the "
    "prompt bodies are proprietary and raise `NotImplementedError` in this build. "
    "Everything else — the orchestration, the schema, the gates — is real code."
)


def module_docstring(module: str) -> str:
    tree = ast.parse((SALES / module / "agent.py").read_text(encoding="utf-8"))
    return (ast.get_docstring(tree) or "").strip()


def page(module: str, title: str, prefix: str, profile: str, gate: str, full: bool) -> str:
    doc = module_docstring(module)
    # The docstring's own first line is a title line; the heading replaces it.
    body = "\n".join(doc.splitlines()[1:]).strip()
    return f"""# {title}

| | |
|---|---|
| **Module** | `backend/agents/sales/{module}/` |
| **Routes** | `{prefix}` |
| **Mind profile** | `{profile}` |
| **Human gate** | {gate} |

{FULL if full else WITHHELD}

---

{body}

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for module, title, prefix, profile, gate, full in AGENTS:
        target = OUT / f"{module.replace('_', '-')}.md"
        target.write_text(page(module, title, prefix, profile, gate, full), encoding="utf-8")
        print(f"   {target.relative_to(ROOT)}")
    print(f"\n{len(AGENTS)} agent pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
