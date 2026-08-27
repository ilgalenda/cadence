#!/usr/bin/env bash
#
# Sync the public Cadence showcase from the internal working tree.
#
# The internal repo carries live operational content: the knowledge vault, per-user
# call learnings, the user roster, session stores. None of it may reach this repo.
# So this script works by ALLOWLIST — it copies only the paths named below, and
# refuses to run if any of them is missing. It never mirrors a directory wholesale
# and then deletes; a deletion that silently fails would publish the data.
#
# The internal tree is read-only here. No git command in this script touches it.
#
# Usage:  tools/sync-from-internal.sh [path-to-internal-checkout]

set -euo pipefail

INTERNAL="${1:-$HOME/Developer/cadence-internal}"
PUBLIC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -d "$INTERNAL/backend" ]] || { echo "No internal checkout at $INTERNAL" >&2; exit 1; }
[[ -d "$PUBLIC/.git"     ]] || { echo "$PUBLIC is not a git repo" >&2; exit 1; }

# A second remote in this clone would make an accidental push to the wrong place
# possible. There must be exactly one, and it must be the public repo.
remotes=$(git -C "$PUBLIC" remote)
[[ "$remotes" == "origin" ]] || { echo "Expected exactly one remote 'origin', found: $remotes" >&2; exit 1; }
git -C "$PUBLIC" remote get-url origin | grep -q 'ilgalenda/cadence' \
  || { echo "origin is not ilgalenda/cadence — refusing to sync" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Never copied, under any path. Applied to every rsync below, so a new data file
# appearing inside an allowlisted directory is excluded by default rather than
# published by default.
# ---------------------------------------------------------------------------
EXCLUDES=(
  # Operational content and state
  --exclude 'vault/'
  --exclude 'data/'
  --exclude 'knowledge/'
  --exclude 'users.json'
  --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm'
  --exclude '*.json.bak' --exclude '*.bak'
  # Secrets. The include must precede the exclude it carves out of, and the
  # token/secret patterns are deliberately narrow: a blanket '*token*' would
  # also swallow the design system's tokens.css.
  --include '.env.example'
  --exclude '.env' --exclude '.env.*'
  --exclude 'google_tokens.json' --exclude '*_secret*' --exclude '*_credentials*'
  --exclude '*apikey*' --exclude '*api_key*'
  --exclude '*.pem' --exclude '*.key' --exclude '*.p12' --exclude '*.pfx'
  # The proprietary prompt library — stubbed separately, never copied
  --exclude 'prompts.py'
  --exclude 'signal_prompts.py'
  # Build, tooling and OS noise
  --exclude '__pycache__/' --exclude '*.pyc'
  --exclude '.venv/' --exclude 'node_modules/' --exclude 'dist/' --exclude '.astro/'
  --exclude '.claude/' --exclude '.obsidian/' --exclude '.DS_Store'
  --exclude '.pytest_cache/' --exclude '.ruff_cache/' --exclude '.mypy_cache/'
)

# ---------------------------------------------------------------------------
# Superseded by the 2.0 architecture. Removed from the public tree so the repo
# stops advertising agents that no longer exist. Their history stays in git.
#
# NOT listed here, and deliberately kept: duty, forecast, onboarding, meet.
# Those become the Operations section — part two, not yet on the Owl Mind.
# ---------------------------------------------------------------------------
SUPERSEDED=(
  backend/agents/calls
  backend/agents/lead
  backend/agents/high_intent
  frontend/src/agents
  frontend/src/components/lead
  frontend/src/pages/agents/calls
  frontend/src/pages/agents/lead
  frontend/src/pages/agents/high-intent
  # High-Intent does not exist in 2.0; its doc page must not outlive it.
  docs/agents/high-intent.md
  frontend/src/pages/agents/owl
  frontend/src/pages/agents
  # Astro build cache, tracked at v1 by accident.
  frontend/.astro
  # One-off data migrations and a v1 enrichment script that imports a deleted
  # agent. They document data shapes, not architecture.
  backend/enrich_vault.py
  backend/migrate_learnings.py
  backend/migrate_owl_sqlite.py
  backend/migrate_owners.py
  backend/migrate_to_vault.py
)

# ---------------------------------------------------------------------------
# The allowlist. Directories are copied recursively (minus EXCLUDES); files are
# copied as named. A missing source path is a hard error, not a warning — it
# means the internal tree moved and the allowlist is now lying about coverage.
# ---------------------------------------------------------------------------
DIRS=(
  # The Owl Mind: the single governed LLM gateway
  backend/agents/mind
  # Capability services and third-party integrations
  backend/agents/services
  backend/integrations
  # Shared engineering layer: vault loader, contributions, json store
  backend/agents/shared
  # The eleven sales agents, plus their orchestration
  backend/agents/sales
  # Surfaces: workspace, wiki, learn, admin
  backend/agents/owl
  backend/agents/wiki
  backend/agents/learn
  backend/agents/admin
  # Evidence that the platform is test-driven
  backend/tests
  # The studio design system, ratified 2026-08-20
  frontend/src/design-system
  frontend/src/lib
  frontend/src/components
  frontend/src/layouts
  frontend/src/pages
  frontend/src/styles
  # Build config and the design-system adherence gates. Without these the copied
  # 2.0 source builds against v1 Tailwind config and fails on its own token classes.
  frontend/scripts
  frontend/public
  bin
)

FILES=(
  backend/main.py
  backend/auth.py
  backend/paths.py
  backend/import_contributions.py
  backend/contributions.template.json
  backend/requirements.txt
  backend/pytest.ini
  backend/.env.example
  frontend/astro.config.mjs
  frontend/tailwind.config.mjs
  frontend/package.json
  frontend/package-lock.json
  package.json
  LICENSE
)

# ---------------------------------------------------------------------------
# The Operations set: the v1 layer the kept Operations agents still depend on.
# The wholesale directory copies above wipe these, so they come back from git.
#
# Their dependency on agents.shared.anthropic_client is precisely what the Owl
# Mind integration removes — it is left visible rather than papered over.
#
# Their v1 *frontend* is not kept. It does not build (it touches `document` at
# build time), it is outside the design system, and it is the first thing a
# studio rebuild would delete. The agents, their tests and their docs stay.
# ---------------------------------------------------------------------------
OPERATIONS=(
  backend/agents/shared/anthropic_client.py
  backend/agents/shared/jsonstore.py
  backend/tests/test_duty.py
  backend/tests/test_forecast.py
  backend/tests/test_pipeline_manager.py
)

echo "internal : $INTERNAL"
echo "public   : $PUBLIC"
echo

echo "→ removing superseded v1 paths"
for path in "${SUPERSEDED[@]}"; do
  if [[ -e "$PUBLIC/$path" ]]; then
    rm -rf "${PUBLIC:?}/$path"
    echo "   removed  $path"
  fi
done
echo

echo "→ copying allowlisted directories"
for dir in "${DIRS[@]}"; do
  [[ -d "$INTERNAL/$dir" ]] || { echo "MISSING source dir: $dir" >&2; exit 1; }
  rm -rf "${PUBLIC:?}/$dir"
  mkdir -p "$PUBLIC/$dir"
  rsync -a "${EXCLUDES[@]}" "$INTERNAL/$dir/" "$PUBLIC/$dir/"
  echo "   $(find "$PUBLIC/$dir" -type f | wc -l | tr -d ' ')\tfiles  $dir"
done
echo

echo "→ copying allowlisted files"
for file in "${FILES[@]}"; do
  [[ -f "$INTERNAL/$file" ]] || { echo "MISSING source file: $file" >&2; exit 1; }
  mkdir -p "$PUBLIC/$(dirname "$file")"
  cp "$INTERNAL/$file" "$PUBLIC/$file"
  echo "   copied   $file"
done
echo

echo "→ restoring the Operations set (v1, kept deliberately)"
for path in "${OPERATIONS[@]}"; do
  git -C "$PUBLIC" checkout -- "$path" 2>/dev/null && echo "   restored $path"
done
echo

echo "→ dropping tests that exercise excluded code"
# Two kinds. The one-off data migrations are not published (they document data
# shapes, not architecture), so the test importing them cannot collect. And a
# test that drives a withheld prompt tests nothing: it would fail on a redaction
# working exactly as intended, which reads as a broken repository. The suites
# that remain cover the code this build actually contains, and they pass.
for dropped in \
  test_vault_migrations.py \
  test_composer.py \
  test_research.py \
  test_campaign_intelligence.py \
  test_call_analysis.py \
  test_mail_draft.py \
  test_signals.py \
  test_learn_quiz.py
do
  rm -f "$PUBLIC/backend/tests/$dropped"
  echo "   dropped  tests/$dropped"
done
echo

echo "→ applying public-build-only patches"
"$PUBLIC/tools/patch-public-build.py"
echo

echo "→ redacting the prompt library"
for module in \
  backend/agents/sales/prompts.py \
  backend/agents/sales/signal_prompts.py \
  backend/agents/learn/prompts.py
do
  "$PUBLIC/tools/redact-prompts.py" "$INTERNAL" "$module" > "$PUBLIC/$module"
  echo "   redacted $module"
done
echo

echo "→ vault ships as empty scaffolding only"
for pillar in company dynamic added; do
  mkdir -p "$PUBLIC/backend/vault/$pillar"
  touch "$PUBLIC/backend/vault/$pillar/.gitkeep"
done

echo "→ removing the employer brand logo (this build is unbranded)"
rm -f "$PUBLIC"/frontend/public/images/*-logo.png

echo
echo "Done. Nothing has been staged or committed."
echo "Run the leak gate before you even think about git add:  tools/leak-gate.sh"
