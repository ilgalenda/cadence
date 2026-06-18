#!/usr/bin/env python3
"""Cadence Agent Creator — scaffold a new agent from its platform parameters.

A Cadence agent is a backend dir (`backend/agents/<mod>/`) plus a frontend
config + page, wired through `paths.py`, `main.py`, the dashboard, and the
seeded user profiles. This tool emits all of that from one small spec so a new
agent is minutes, not an afternoon of boilerplate.

Usage (from the repo root or anywhere):

    python backend/scripts/create_agent.py --spec backend/scripts/specs/duty.json
    python backend/scripts/create_agent.py --slug duty --name "Duty & Tax" \
        --tagline "Autonomous shipment duty & tax calculator" --kind tool --entity quote
    python backend/scripts/create_agent.py --spec backend/scripts/specs/duty.json --dry-run

Spec fields (JSON, or the matching --flags):
    slug      url/route slug, e.g. "duty" or "high-intent"   (required)
    name      display name, e.g. "Duty & Tax"                (required)
    tagline   one-line description                           (required)
    icon      emoji/glyph for the nav                        (default "◆")
    kind      simple | crud | chat | tool                    (default "crud")
    entity    singular record name, e.g. "quote"             (default "item")
    status    active | test | coming-soon (dashboard badge)  (default "active")

The tool refuses to overwrite an existing agent, and is otherwise idempotent at
the wiring level (it won't double-insert an import/router/path helper). Pass
--dry-run to print the file plan without writing anything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent          # .../backend
REPO = BACKEND.parent                                       # repo root
FRONTEND = REPO / "frontend"
TEMPLATES = Path(__file__).resolve().parent / "templates" / "agent"

# Anchors inserted once into the host files (see those files).
PATHS_ANCHOR = "# >>> cadence:paths"
MAIN_IMPORTS_ANCHOR = "# >>> cadence:agent-imports"
MAIN_ROUTERS_ANCHOR = "# >>> cadence:agent-routers"
DASHBOARD_ANCHOR = "// >>> cadence:agents"


def build_vars(spec: dict) -> dict:
    slug = spec["slug"].strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", slug):
        sys.exit(f"error: slug '{slug}' must be lowercase letters/digits/hyphens, starting with a letter")
    mod = slug.replace("-", "_")
    entity = (spec.get("entity") or "item").strip().lower()
    entity_plural = spec.get("entity_plural") or (entity + "s")
    return {
        "SLUG": slug,
        "MOD": mod,
        "CONST": mod.upper(),
        "NAME": spec["name"].strip(),
        "TAGLINE": spec["tagline"].strip().rstrip("."),
        "ICON": spec.get("icon") or "◆",
        "KIND": spec.get("kind") or "crud",
        "STATUS": spec.get("status") or "active",
        "ENTITY": entity,
        "ENTITY_TITLE": entity.title(),
        "ENTITY_PLURAL": entity_plural,
    }


def render(template_name: str, v: dict) -> str:
    text = (TEMPLATES / template_name).read_text()
    for key, val in v.items():
        text = text.replace(f"@@{key}@@", str(val))
    return text


def insert_before(path: Path, anchor: str, block: str, *, skip_if_contains: str, dry: bool) -> str:
    """Insert `block` immediately before the line containing `anchor`.

    Returns a status string. No-ops (idempotent) if `skip_if_contains` is
    already present in the file.
    """
    text = path.read_text()
    if anchor not in text:
        sys.exit(f"error: anchor '{anchor}' not found in {path} — was it removed?")
    if skip_if_contains and skip_if_contains in text:
        return f"  skip   {path.relative_to(REPO)} (already wired)"
    new_text = text.replace(anchor, block + anchor, 1)
    if not dry:
        path.write_text(new_text)
    return f"  edit   {path.relative_to(REPO)}"


def wire_seed_users(v: dict, dry: bool) -> str:
    """Append the slug to every profile's `agents` list in seed_users.py."""
    path = BACKEND / "seed_users.py"
    if not path.exists():
        return "  note   backend/seed_users.py not found — add the slug to your user profiles manually"
    text = path.read_text()
    slug = v["SLUG"]

    def add(match: re.Match) -> str:
        inner = match.group(1)
        if f'"{slug}"' in inner:
            return match.group(0)
        sep = ", " if inner.strip() else ""
        return f'"agents": [{inner}{sep}"{slug}"]'

    new_text = re.sub(r'"agents":\s*\[([^\]]*)\]', add, text)
    if new_text == text:
        return "  skip   backend/seed_users.py (already lists slug)"
    if not dry:
        path.write_text(new_text)
    return "  edit   backend/seed_users.py (added slug to profiles)"


def next_dashboard_index(text: str) -> str:
    n = len(re.findall(r"href:\s*'/agents/", text)) + 1
    return str(n).zfill(2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a new Cadence agent.")
    ap.add_argument("--spec", help="path to a JSON spec file")
    ap.add_argument("--slug")
    ap.add_argument("--name")
    ap.add_argument("--tagline")
    ap.add_argument("--icon")
    ap.add_argument("--kind", choices=["simple", "crud", "chat", "tool"])
    ap.add_argument("--entity")
    ap.add_argument("--status", choices=["active", "test", "coming-soon"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.spec:
        spec = json.loads(Path(args.spec).read_text())
    else:
        spec = {}
    for key in ("slug", "name", "tagline", "icon", "kind", "entity", "status"):
        if getattr(args, key, None):
            spec[key] = getattr(args, key)
    for required in ("slug", "name", "tagline"):
        if not spec.get(required):
            sys.exit(f"error: '{required}' is required (via --{required} or the spec file)")

    v = build_vars(spec)
    dry = args.dry_run
    agent_dir = BACKEND / "agents" / v["MOD"]
    if agent_dir.exists():
        sys.exit(f"error: {agent_dir.relative_to(REPO)} already exists — refusing to overwrite")

    plan: list[str] = []

    # --- backend files ---
    files: list[tuple[Path, str]] = [
        (agent_dir / "__init__.py", ""),
        (agent_dir / "routes.py", render("routes.py.tmpl", v)),
        (agent_dir / "storage.py", render("storage.py.tmpl", v)),
        (FRONTEND / "src" / "agents" / v["SLUG"] / "config.ts", render("config.ts.tmpl", v)),
        (FRONTEND / "src" / "pages" / "agents" / v["SLUG"] / "index.astro", render("index.astro.tmpl", v)),
    ]
    for path, content in files:
        plan.append(f"  create {path.relative_to(REPO)}")
        if not dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    # --- wiring (anchored, idempotent) ---
    plan.append(insert_before(
        BACKEND / "paths.py", PATHS_ANCHOR,
        f"# {v['NAME']}\ndef {v['MOD']}_data() -> Path:\n"
        f'    return data_root() / "agents" / "{v["MOD"]}" / "data"\n\n\n',
        skip_if_contains=f"def {v['MOD']}_data(", dry=dry,
    ))
    plan.append(insert_before(
        BACKEND / "main.py", MAIN_IMPORTS_ANCHOR,
        f"from agents.{v['MOD']}.routes import router as {v['MOD']}_router\n",
        skip_if_contains=f"agents.{v['MOD']}.routes import", dry=dry,
    ))
    plan.append(insert_before(
        BACKEND / "main.py", MAIN_ROUTERS_ANCHOR,
        f"app.include_router({v['MOD']}_router)\n",
        skip_if_contains=f"include_router({v['MOD']}_router)", dry=dry,
    ))
    dash = FRONTEND / "src" / "pages" / "dashboard.astro"
    idx = next_dashboard_index(dash.read_text())
    plan.append(insert_before(
        dash, DASHBOARD_ANCHOR,
        f"  {{\n    index: '{idx}',\n    href: '/agents/{v['SLUG']}',\n"
        f"    name: '{v['NAME']}',\n    description: '{v['TAGLINE']}.',\n"
        f"    status: '{v['STATUS']}',\n  }},\n  ",
        skip_if_contains=f"href: '/agents/{v['SLUG']}'", dry=dry,
    ))
    plan.append(wire_seed_users(v, dry))

    header = "DRY RUN — no files written\n" if dry else ""
    print(f"{header}Agent '{v['SLUG']}' ({v['KIND']}):")
    print("\n".join(plan))
    if not dry:
        print(
            f"\nNext: run `python backend/seed_users.py --rewrite-profiles` to grant access, "
            f"then build out backend/agents/{v['MOD']}/ and the frontend page."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
