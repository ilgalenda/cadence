#!/usr/bin/env python3
"""Public-build-only adjustments applied after a sync.

These are changes that are correct *here* and would be wrong in the internal
repository, so they are applied as a post-sync step rather than upstream.
Idempotent: running twice changes nothing.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def skip_persona_test_without_a_vault() -> str:
    """`test_the_real_persona_file_strips_cleanly` reads Persona.md from the vault.

    The public build ships the vault as empty scaffolding, so the file is absent
    and the test fails on the absence of data rather than on a defect. Guard it
    with a skip instead: no vault, nothing to strip, nothing to assert.
    """
    path = ROOT / "backend" / "tests" / "test_xray_honesty.py"
    source = path.read_text(encoding="utf-8")
    if "no customer personas in this vault" in source:
        return "   already guarded  tests/test_xray_honesty.py"

    before = '''    text, source = blocks.load_customer_personas_with_source()

    assert source in {"data_root", "repo"}, "Persona.md is missing from both vaults"'''
    after = '''    text, source = blocks.load_customer_personas_with_source()

    if source == "missing":
        pytest.skip("no customer personas in this vault — the public build ships none")
    assert source in {"data_root", "repo"}, "Persona.md is missing from both vaults"'''
    if before not in source:
        return "   SKIPPED  tests/test_xray_honesty.py no longer has the expected shape"
    source = source.replace(before, after, 1)
    if "import pytest" not in source:
        source = source.replace("\nimport ", "\nimport pytest\nimport ", 1)
    path.write_text(source, encoding="utf-8")
    return "   guarded  tests/test_xray_honesty.py against an empty vault"


def retire_high_intent() -> list[str]:
    """High-Intent does not exist in 2.0, so nothing may still advertise it.

    Its package and pages were removed with the rest of the superseded v1 code,
    but several surfaces still named it: a grant type, a seeded roster, optional
    integrations in `.env.example`, and a row in three design-system preview
    screens — which is the one a reader actually sees, because those screens are
    the published screenshots.

    Deliberately left alone: the changelog in `lib/version.ts` and the docstrings
    recording that `high_intent` was retired. That is history, and a changelog
    that edits out what happened is worth nothing. `pins.test.ts` also keeps it
    on purpose, as its example of a slug for an agent that no longer exists.
    """
    notes: list[str] = []

    grant = ROOT / "frontend" / "src" / "lib" / "platform.ts"
    source = grant.read_text(encoding="utf-8")
    before = "export type Grant = 'lead' | 'calls' | 'high-intent';"
    after = "export type Grant = 'lead' | 'calls';"
    if before in source:
        grant.write_text(source.replace(before, after, 1), encoding="utf-8")
        notes.append("   dropped the high-intent grant  lib/platform.ts")

    seed = ROOT / "backend" / "seed_users.py"
    source = seed.read_text(encoding="utf-8")
    before = '"agents": ["calls", "lead", "high-intent", "duty", "onboarding", "forecast"],'
    after = '"agents": ["calls", "lead", "duty", "onboarding", "forecast"],'
    if before in source:
        seed.write_text(source.replace(before, after, 1), encoding="utf-8")
        notes.append("   dropped the high-intent grant  seed_users.py")

    env = ROOT / "backend" / ".env.example"
    source = env.read_text(encoding="utf-8")
    before = """# High-Intent agent — optional integrations (Phase 2)
# PHANTOMBUSTER_API_KEY=      # deeper LinkedIn scraping
# DRIPIFY_API_KEY=            # automated campaign execution
# DRIPIFY_WEBHOOK_SECRET=     # reply event handling

"""
    if before in source:
        env.write_text(source.replace(before, "", 1), encoding="utf-8")
        notes.append("   dropped the high-intent integrations  .env.example")

    preview = ROOT / "frontend" / "src" / "design-system" / "preview"
    for screen in sorted(preview.glob("screen-*.html")):
        source = screen.read_text(encoding="utf-8")
        if "High-Intent" not in source:
            continue
        lines = source.splitlines(keepends=True)
        label = next(i for i, line in enumerate(lines) if "High-Intent" in line)
        # The row is a <div class="ds-row"> … </div> block around the label.
        start = next(i for i in range(label, -1, -1) if 'class="ds-row"' in lines[i])
        end = next(i for i in range(label, len(lines)) if lines[i].strip() == "</div>")
        screen.write_text("".join(lines[:start] + lines[end + 1:]), encoding="utf-8")
        notes.append(f"   removed the High-Intent rail row  preview/{screen.name}")

    return notes or ["   already retired  high-intent"]


def match_the_avatar_to_the_name() -> list[str]:
    """The preview screens draw an avatar as a single letter, hard-coded.

    `genericise.py` renames the person in those screens, but it cannot touch a
    bare initial — one letter matches nothing and could not safely be replaced by
    substring anyway. So the published screenshots showed the original owner's
    initial beside the invented name, which is the sort of detail a careful
    reader notices and an incautious one does not.

    Correct here and wrong upstream: internally the initial is right.
    """
    initial = "S"  # Sam, the invented owner these screens are genericised to.
    preview = ROOT / "frontend" / "src" / "design-system" / "preview"
    notes: list[str] = []

    for screen in sorted(preview.glob("*.html")):
        source = original = screen.read_text(encoding="utf-8")
        for avatar in ('class="ws-user__avatar">', 'ds-avatar--ink">'):
            # Only a single letter, and only inside an avatar: never prose.
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                source = source.replace(f"{avatar}{letter}<", f"{avatar}{initial}<")
        if source != original:
            screen.write_text(source, encoding="utf-8")
            notes.append(f"   matched the avatar to the name  preview/{screen.name}")

    return notes or ["   already matched  preview avatars"]


def main() -> int:
    print(skip_persona_test_without_a_vault())
    for note in retire_high_intent():
        print(note)
    for note in match_the_avatar_to_the_name():
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
