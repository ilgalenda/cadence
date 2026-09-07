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
import re
import sys
from pathlib import Path
from typing import NamedTuple

SKIP_DIRS = {".git", "node_modules", ".astro", "dist", "__pycache__", ".venv", "docs"}
# LICENSE keeps the author's real name: it is the copyright line, not branding.
#
# README.md is hand-written and never synced, so there is nothing in it to
# genericise — and running over it does damage. It explains what the Acme
# placeholder stands for, and substituting inside that explanation turned it into
# "Acme is a stand in for Acme" and shipped it (2026-09-07). A file a person
# writes and reads is not the same problem as a file the sync copies.
SKIP_FILES = {"genericise.py", "genericise.map.json", "sync-from-internal.sh",
              "leak-gate.sh", "LICENSE", "README.md"}
DOTFILES = {".gitignore", ".env.example"}
TEXT_SUFFIXES = {
    # `.mjs` was missing until 2026-09-07, so every ES-module script in
    # `frontend/scripts/` went through un-genericised. The smoke test names the
    # employer and a colleague in its fixture transcript; nothing had rewritten it.
    ".py", ".ts", ".js", ".mjs", ".astro", ".css", ".html", ".md", ".json", ".txt",
    ".sh", ".ini", ".tmpl", ".example", ".yml", ".yaml",
}

# The substitution table lives in tools/genericise.map.json, which is gitignored.
# It has to name the employer in order to remove it, so committing it would put
# back exactly what this script exists to take out. The map is (find, replace)
# pairs, ordered longest-first: anything containing the company name as a
# substring must come before the bare name.
MAP_PATH = Path(__file__).resolve().parent / "genericise.map.json"


class Substitution(NamedTuple):
    """One replacement, and whether it may land inside a longer word.

    Most finds are long and distinctive — a company name, a hostname, a filename —
    and a plain substring replacement is right for them.

    A **short** find is a different problem. A two-letter first name cannot be
    replaced by substring: it would rewrite `Model`, `Module`, `Monitor` and
    `Moment` throughout the build. Those entries set ``word``, which anchors the
    match to word boundaries so only the name itself is touched.
    """

    find: str
    replace: str
    word: bool = False

    def apply(self, text: str) -> str:
        if not self.word:
            return text.replace(self.find, self.replace)
        return re.sub(rf"\b{re.escape(self.find)}\b", self.replace, text)


def load_substitutions() -> list[Substitution]:
    """Read the map. Entries take either form:

        ["find", "replace"]                              substring
        {"find": …, "replace": …, "word": true}          whole word only
    """
    if not MAP_PATH.exists():
        raise SystemExit(
            f"No substitution map at {MAP_PATH}.\n"
            "It is deliberately not committed — see the note above. Recreate it as a\n"
            'JSON array of ["find", "replace"] pairs, ordered longest-first.\n'
            'A short name that would match inside longer words takes the object\n'
            'form instead: {"find": "..", "replace": "..", "word": true}.'
        )

    entries = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    substitutions = []
    for entry in entries:
        if isinstance(entry, dict):
            substitutions.append(
                Substitution(entry["find"], entry["replace"], bool(entry.get("word")))
            )
        else:
            find, replace = entry
            substitutions.append(Substitution(find, replace))
    return substitutions


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


def genericise(text: str, substitutions: list[Substitution]) -> str:
    for substitution in substitutions:
        text = substitution.apply(text)
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
