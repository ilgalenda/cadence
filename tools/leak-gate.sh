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
  names=$(python3 -c "
import json, re, sys
pairs = json.load(open('tools/genericise.map.json', encoding='utf-8'))
# Only the word-shaped finds; the path and email substitutions are covered elsewhere.
words = {f.lower() for f, _ in pairs if re.fullmatch(r'[A-Za-z][A-Za-z0-9 .+-]{2,}', f)}
print('|'.join(re.escape(w) for w in sorted(words)))
")
  if hits=$(scan "(${names})" | grep -iv '^./LICENSE'); then
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

note "6. Size sanity"
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
