#!/usr/bin/env python3
"""Produce the public prompt module from the internal one.

The prompt library is the commercial edge of Cadence, so it does not travel to
the public showcase. But the agents import it, and shipping a repo whose imports
fail teaches a reader nothing. So this rewrites the module instead of dropping it:

  * the prompts belonging to the three exemplar agents (Lead Scoring, GTM, X-ray)
    are kept verbatim, so a reader can see real prompt engineering;
  * every other prompt keeps its NAME, SIGNATURE and DOCSTRING — the contract —
    and loses its body.

Withheld callables raise NotImplementedError; withheld constants become a short
placeholder string. Nothing silently returns an empty prompt.

Run from the public repo root:
    tools/redact-prompts.py <internal-checkout> <relative/path/to/prompts.py>
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# The exemplar agents' prompts, kept in full. Private helpers these depend on are
# pulled in automatically below, so this list stays readable. Every prompt module
# not named here is redacted in full.
KEEP_BY_MODULE = {"backend/agents/sales/prompts.py": {
    # Lead Scoring — the deterministic-core exemplar
    "CLAUDE_BASE_SYSTEM",
    "claude_signal_prompt",
    # GTM — the ungrounded analyze exemplar
    "GTM_TARGETS_SYSTEM",
    "gtm_targets_user_prompt",
    # X-ray — the checker that verifies GTM
    "XRAY_SYSTEM_PROMPT",
    "GROUNDING_SYSTEM_PROMPT",
    "grounding_user_message",
    "xray_system_prompt",
    "xray_user_payload",
    "xray_user_message",
}}

WITHHELD_NOTE = (
    "Withheld from the public showcase — the prompt library is proprietary. "
    "The signature and docstring above are the full contract this prompt satisfies; "
    "see docs/agents/ for what it is asked to produce."
)

HEADER = '''"""Prompt library — public showcase build.

Cadence keeps every prompt in one module so they can be reviewed, diffed and
version-controlled as a body of work rather than scattered through agent code.

This is the redacted build of that module. The prompts for the three exemplar
agents are present in full; the rest keep their signatures and docstrings and
lose their bodies. Regenerate with tools/redact-prompts.py — do not hand-edit.
"""
'''


def top_level_name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    return None


def names_used_by(node: ast.stmt) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def resolve_kept_helpers(nodes: list[ast.stmt], keep: set[str]) -> set[str]:
    """Widen `keep` to cover the private helpers the kept prompts call.

    Iterates to a fixed point, so a helper that calls another helper is included.
    """
    by_name = {top_level_name(n): n for n in nodes if top_level_name(n)}
    resolved = set(keep)
    while True:
        grown = set(resolved)
        for name in resolved:
            node = by_name.get(name)
            if node is None:
                continue
            grown |= {u for u in names_used_by(node) if u.startswith("_") and u in by_name}
        if grown == resolved:
            return resolved
        resolved = grown


def redact_callable(node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> str:
    signature_end = node.body[0].lineno - 1
    lines = source.splitlines()[node.lineno - 1 : signature_end]
    doc = ast.get_docstring(node)
    contract = "\n".join(f"    {line}".rstrip() for line in doc.splitlines()) + "\n\n" if doc else ""
    body = [f'    """\n{contract}    {WITHHELD_NOTE}\n    """']
    body.append(f'    raise NotImplementedError("{node.name} is withheld from the public build.")')
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]
    return "\n".join(decorators + lines + body)


def is_prompt_text(node: ast.Assign) -> bool:
    """True when the assigned value is prompt text rather than structure.

    Only string constants are withheld. Tuples, dicts and the like are the shapes
    the agents index into (COMPOSER_CHANNELS, _COMPOSER_SHAPES); replacing those
    with a string would not redact a prompt, it would break the module.
    """
    value = node.value
    return isinstance(value, ast.JoinedStr) or (
        isinstance(value, ast.Constant) and isinstance(value.value, str)
    )


def redact_constant(name: str) -> str:
    return f'{name} = "<withheld from the public build — see docs/agents/>"'


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    internal, relative = Path(sys.argv[1]), sys.argv[2]
    source = (internal / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    requested = KEEP_BY_MODULE.get(relative, set())
    keep = resolve_kept_helpers(tree.body, requested) if requested else set()
    unknown = requested - {top_level_name(n) for n in tree.body if top_level_name(n)}
    if unknown:
        print(f"KEEP names not found in {relative}: {sorted(unknown)}", file=sys.stderr)
        return 1

    out: list[str] = [HEADER]
    for node in tree.body:
        name = top_level_name(node)
        if name is None:
            # Imports, __future__, module docstring: keep verbatim except the docstring,
            # which the header above replaces.
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            out.append(ast.get_source_segment(source, node) or "")
        elif name in keep:
            out.append(ast.get_source_segment(source, node) or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(redact_callable(node, source))
        elif isinstance(node, ast.Assign) and is_prompt_text(node):
            out.append(redact_constant(name))
        else:
            out.append(ast.get_source_segment(source, node) or "")

    kept = sorted(n for n in keep)
    print(f"kept {len(kept)} names verbatim: {', '.join(kept)}", file=sys.stderr)
    sys.stdout.write("".join(part + "\n\n" for part in out if part.strip()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
