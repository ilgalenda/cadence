#!/usr/bin/env python3
"""Remove the employer's identity from the public showcase build.

Cadence was built for one company. The architecture is the thing worth showing,
so the public build carries no branding: the platform reads as a platform, and
the company it is configured for is a placeholder (Acme) that a reader can
obviously substitute. Attribution lives in one line of the README instead.

Substitutions are ordered longest-first so the specific ones (hostnames, file
names, field names) land before the bare company name. Applied after every sync;
run it twice and nothing changes.

    tools/genericise.py [--check]

--check reports what would change and exits non-zero if anything would.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".astro", "dist", "__pycache__", ".venv", "docs"}
# LICENSE keeps the author's real name: it is the copyright line, not branding.
SKIP_FILES = {"genericise.py", "genericise.map.json", "sync-from-internal.sh", "leak-gate.sh", "LICENSE"}
DOTFILES = {".gitignore", ".env.example"}
TEXT_SUFFIXES = {
    ".py", ".ts", ".js", ".astro", ".css", ".html", ".md", ".json", ".txt",
    ".sh", ".ini", ".tmpl", ".example", ".yml", ".yaml",
}

# The substitution table lives in tools/genericise.map.json, which is gitignored.
# It has to name the employer in order to remove it, so committing it would put
# back exactly what this script exists to take out. The map is (find, replace)
# pairs, ordered longest-first: anything containing the company name as a
# substring must come before the bare name.
MAP_PATH = Path(__file__).resolve().parent / "genericise.map.json"


def load_substitutions() -> list[tuple[str, str]]:
    if not MAP_PATH.exists():
        raise SystemExit(
            f"No substitution map at {MAP_PATH}.\n"
            "It is deliberately not committed — see the note above. Recreate it as a\n"
            'JSON array of ["find", "replace"] pairs, ordered longest-first.'
        )
    return [(find, replace) for find, replace in json.loads(MAP_PATH.read_text(encoding="utf-8"))]


def candidate_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in DOTFILES:
            files.append(path)
    return files


def genericise(text: str, substitutions: list[tuple[str, str]]) -> str:
    for find, replace in substitutions:
        text = text.replace(find, replace)
    return text


def main() -> int:
    check_only = "--check" in sys.argv
    root = Path(__file__).resolve().parent.parent
    substitutions = load_substitutions()
    changed = []
    for path in candidate_files(root):
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rewritten = genericise(original, substitutions)
        if rewritten == original:
            continue
        changed.append(path.relative_to(root))
        if not check_only:
            path.write_text(rewritten, encoding="utf-8")

    verb = "would change" if check_only else "rewrote"
    for path in changed:
        print(f"   {verb}  {path}")
    print(f"\n{len(changed)} files {verb}")
    return 1 if (check_only and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
