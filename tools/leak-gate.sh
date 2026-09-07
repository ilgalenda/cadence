#!/usr/bin/env bash
#
# The last check before anything is pushed to a public repository.
#
# Publishing is irreversible: a secret or a client name that reaches GitHub has
# reached it, whether or not a later commit removes it. So this fails loudly and
# fails closed — any hit is an exit 1, and the operator reads the file list.
#
# Run against the working tree before `git add`, and again against a fresh clone
# after the push. The second run is the one that tests what is actually public.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
note() { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAIL=1; }
pass() { printf '  ok    %s\n' "$1"; }

# Search the tracked-or-untracked working tree, not the git history.
scan() { grep -rInE "$1" . \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.astro \
    --exclude-dir=dist --exclude-dir=__pycache__ --exclude-dir=.venv \
    --exclude-dir=.pytest_cache --exclude-dir=.ruff_cache \
    --exclude=genericise.map.json --exclude=leak-gate.sh 2>/dev/null; }

# The same search, case-insensitively. A name that only has to be spelled
# differently to get past the gate is not a gate.
scan_i() { grep -rInEi "$1" . \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.astro \
    --exclude-dir=dist --exclude-dir=__pycache__ --exclude-dir=.venv \
    --exclude-dir=.pytest_cache --exclude-dir=.ruff_cache \
    --exclude=genericise.map.json --exclude=leak-gate.sh 2>/dev/null; }

note "1. Operational content must not be present as files"
for pattern in \
  './backend/vault/*/*.md' \
  './backend/agents/*/data/*.json' \
  './backend/agents/*/knowledge/_user' \
  './backend/agents/users.json' \
  './frontend/.astro/*'
do
  # shellcheck disable=SC2086
  found=$(find . -path "$pattern" -not -path './.git/*' 2>/dev/null | head -5)
  if [[ -n "$found" ]]; then fail "$pattern"; echo "$found" | sed 's/^/        /'
  else pass "$pattern"; fi
done
if find . -name '*.db' -not -path './.git/*' -not -path './node_modules/*' | grep -q .; then
  fail "a SQLite database is present"
else pass "no *.db"; fi
if [[ -f backend/.env ]]; then fail "backend/.env is present"; else pass "no backend/.env"; fi

note "2. Secrets"
if hits=$(scan '(sk-ant-[A-Za-z0-9_-]{8}|AIza[A-Za-z0-9_-]{20}|-----BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._-]{20})'); [[ -n "$hits" ]]; then
  fail "credential-shaped string"; echo "$hits" | head -10 | sed 's/^/        /'
else pass "no credential-shaped strings"; fi
# A populated secret in .env.example is the classic accident: keys are named there,
# so only a non-empty assignment is a finding.
if hits=$(grep -nE '^(ANTHROPIC_API_KEY|LUSHA_API_KEY|SESSION_SECRET|GOOGLE_CLIENT_SECRET|SMTP_PASSWORD|[A-Z_]*PASSWORD)=.+' backend/.env.example 2>/dev/null); then
  fail "populated value in .env.example"; echo "$hits" | sed 's/^/        /'
else pass ".env.example has no populated values"; fi

note "3. The employer, real accounts and real people"
# The names to hunt for are the find-side of the genericisation map, so this check
# never drifts from the substitution that is supposed to have removed them. The map
# is gitignored (it has to name the employer in order to remove it), which is also
# why this file is excluded from genericisation — otherwise the gate would end up
# searching for its own replacements.
if [[ -f tools/genericise.map.json ]]; then
  # The pattern mirrors the map's own semantics, so the gate checks exactly what
  # the genericiser promised to remove:
  #   * a `word` entry is anchored, because a bare two-letter name would
  #     otherwise match inside Model, Module and Monitor;
  #   * everything else is a plain substring, as the substitution was.
  # Matched case-insensitively. The previous version lower-cased the names and
  # then grepped case-sensitively, so a name spelled in any other case — an
  # all-caps constant, thirteen times in one module — was invisible to the only
  # check for real people there is. This file excludes itself from the scan, so
  # it can never catch its own examples: keep them generic.
  names=$(python3 -c "
import json, re
entries = json.load(open('tools/genericise.map.json', encoding='utf-8'))
patterns = set()
for entry in entries:
    if isinstance(entry, dict):
        find, word = entry['find'], bool(entry.get('word'))
    else:
        find, word = entry[0], False
    # Word-shaped finds only; paths and emails are covered by checks 2 and 4.
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9 .+-]+', find):
        continue
    patterns.add(rf'\b{re.escape(find)}\b' if word else re.escape(find))
print('|'.join(sorted(patterns)))
")
  if hits=$(scan_i "(${names})" | grep -iv '^./LICENSE'); then
    fail "a name the genericisation map is supposed to have removed"
    echo "$hits" | head -12 | sed 's/^/        /'
  else pass "no names from the genericisation map survive"; fi
else
  fail "tools/genericise.map.json is missing — cannot check for identifying names"
fi
# Test fixtures are full of throwaway addresses (a@b.com and the like). Those are
# reported so a human sees them, but only an address OUTSIDE the test suites fails
# the gate — that is where a real one would actually do damage.
email_re='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
email_ok='@(acme\.example|example\.(com|org|net)|northgate\.com|sentry\.io|schema\.org|w3\.org|googleapis\.com|gstatic\.com)'
all_emails=$(scan "$email_re" | grep -viE "$email_ok")
outside_tests=$(echo "$all_emails" | grep -vE '(/tests?/|\.test\.|test_[a-z_]+\.py)' | grep -v '^$')
in_tests=$(echo "$all_emails" | grep -E '(/tests?/|\.test\.|test_[a-z_]+\.py)' | grep -v '^$')
if [[ -n "$outside_tests" ]]; then
  fail "email address outside the test suites"; echo "$outside_tests" | head -10 | sed 's/^/        /'
else pass "no email addresses outside the test suites"; fi
if [[ -n "$in_tests" ]]; then
  printf '  note  %s throwaway addresses in test fixtures — read them:\n' "$(echo "$in_tests" | wc -l | tr -d ' ')"
  echo "$in_tests" | head -8 | sed 's/^/        /'
fi

note "4. Home directories and machine paths"
if hits=$(scan '/Users/[a-z][a-z0-9]+/' | grep -v '/Users/you/'); then
  fail "a real home directory path"; echo "$hits" | head -5 | sed 's/^/        /'
else pass "no real home directory paths"; fi

note "5. Withheld prompts really are withheld"
for module in backend/agents/sales/prompts.py backend/agents/sales/signal_prompts.py backend/agents/learn/prompts.py; do
  if [[ ! -f "$module" ]]; then fail "$module missing"; continue; fi
  if grep -q 'withheld from the public build' "$module"; then pass "$module is the redacted build"
  else fail "$module is NOT redacted — this may be the internal file"; fi
done

note "6. Commercial figures"
# The price catalogue is confidential and lives outside the repository entirely.
# But figures leak in prose: `valuation.py` explained itself with four real list
# prices, two of which subtract to give a third, and nothing here was looking at
# numbers at all. So any four-or-more-figure money amount has to be one the
# example catalogue already publishes.
#
# `pricing.example.json` is the allowlist because it is deliberately fake — every
# figure in it is a round number, stated in the file itself, so that nobody can
# mistake one for a price.
# An absent catalogue means an empty allowlist, not a skipped check: no example
# figures simply means no money figure is allowed anywhere.
#
# A campaign's goal and a pipeline total are not prices, so they are not in the
# catalogue — but the build needs example ones. They are named here rather than
# inferred, so a reader can see exactly which figures this repository sanctions.
catalogue=backend/agents/outbound/pricing.example.json
#   100000 250000 20000  a campaign goal, a pipeline total, a qualified total
#   1200 1234            synthetic values in the importer fixtures
#   2500 21500           sums the store tests assert, of the fake figures above
SANCTIONED="100000 250000 20000 1200 1234 2500 21500"
allowed=$(python3 -c "
import re
from pathlib import Path
path = Path('$catalogue')
text = path.read_text(encoding='utf-8') if path.exists() else ''
figures = {n for n in re.findall(r'\b\d{4,}\b', text)} | set('$SANCTIONED'.split())
print(' '.join(sorted(figures, key=int)))
")
# Three shapes, and the third is the one that actually got out: the whole real
# catalogue sat in a test fixture as a bare `"price_gbp": 12345` — no £, no
# grouping — and a check looking only for the first two walked straight past it.
#
# A £ sign is money wherever it appears. A bare or grouped number is money only
# when its line says so: `60_000` in a date test is milliseconds, and a check
# that cries wolf about it gets silenced within a week.
MONEY_CONTEXT='gbp|price|cost|value|goal|revenue|budget'
# The bare-integer shape is the noisy one — every landed-cost test and every
# arithmetic fixture in the repository trips it — so it is scoped to the modules
# a price catalogue can actually reach: the tracker, GTM's deal shaping, and the
# tests and views over them. The £ and grouped shapes stay repository-wide,
# because they are precise enough to be quiet anywhere.
PRICED='backend/agents/outbound|backend/agents/sales/gtm|tests/test_outbound|tests/test_gtm|lib/outbound'
money=$( { scan '£[0-9][0-9,]{3,}';
           scan '\b[0-9]+_[0-9]{3}\b' | grep -iE "$MONEY_CONTEXT";
           scan '\b[0-9]{4,7}\b'      | grep -E "$PRICED" | grep -iE "$MONEY_CONTEXT"; } \
         | grep -v "$catalogue" || true)
bad=""
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  figure=$(echo "$line" | grep -oE '(£[0-9][0-9,]{3,}|\b[0-9]+_[0-9]{3}\b|\b[0-9]{4,7}\b)' | head -1 \
           | tr -d '£,_')
  [[ -z "$figure" ]] && continue
  # A year is not a price. Filtered on the figure rather than the line, so a real
  # money line that happens to mention a date is still checked.
  if (( figure >= 1900 && figure <= 2100 )); then continue; fi
  if ! grep -qw -- "$figure" <<<"$allowed"; then bad+="$line"$'\n'; fi
done <<<"$money"
if [[ -n "${bad//[$'\n']}" ]]; then
  fail "a money figure that is not in the example catalogue"
  echo "$bad" | head -10 | sed 's/^/        /'
else pass "no money figures outside the example catalogue"; fi

note "7. Size sanity"
# Files still in the index but deleted from the worktree do not survive the commit,
# so counting them would overstate what is about to be published.
count=$(comm -23 <(git ls-files --cached --others --exclude-standard | sort) <(git ls-files --deleted | sort) | wc -l | tr -d ' ')
printf '  %s files would be published\n' "$count"
if (( count > 450 )); then fail "far more files than expected — the allowlist may have failed"
else pass "file count within range"; fi

printf '\n'
if (( FAIL )); then
  printf '\033[1mLEAK GATE FAILED — do not push.\033[0m\n'
  exit 1
fi
printf '\033[1mLeak gate passed.\033[0m Now read the file list by eye before pushing:\n'
printf '    git ls-files --cached --others --exclude-standard | less\n'
