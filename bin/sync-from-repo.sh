#!/usr/bin/env bash
# sync-from-repo.sh — refresh local DATA_ROOT with the latest committed data.
#
# Use after `git pull` when developing locally with DATA_ROOT pointing outside
# the repo. Copies committed vault + agents data into DATA_ROOT, preserving
# your gitignored users_credentials.json (so your local passwords survive).
#
# Usage:
#   DATA_ROOT=~/cadence-data bin/sync-from-repo.sh
#   # or rely on the default of ~/cadence-data:
#   bin/sync-from-repo.sh
set -euo pipefail

REPO_BACKEND="$(cd "$(dirname "$0")/.." && pwd)/backend"
LOCAL_DATA="${DATA_ROOT:-$HOME/cadence-data}"

if [ ! -d "$REPO_BACKEND" ]; then
  echo "error: expected $REPO_BACKEND to exist" >&2
  exit 1
fi

mkdir -p "$LOCAL_DATA"

rsync -a \
  --exclude 'users_credentials.json' \
  "$REPO_BACKEND/vault" \
  "$REPO_BACKEND/agents" \
  "$LOCAL_DATA/"

echo "synced $REPO_BACKEND → $LOCAL_DATA"
echo "(users_credentials.json preserved — run seed_users.py if you need to (re)create it)"
