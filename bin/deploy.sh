#!/usr/bin/env bash
# deploy.sh — pull the latest code and ship it to production in one step.
#
# Run this ON THE PRODUCTION SERVER. It does everything a deploy needs, in
# order, so the frontend build can't be forgotten (the usual cause of a
# "the UI still looks old" report):
#
#   1. git pull                 — fetch the latest committed code
#   2. npm install              — pick up any new/changed frontend deps
#   3. npm run build            — regenerate frontend/dist/ (the UI the
#                                 backend actually serves)
#   4. restart the backend      — re-serve the freshly built dist/
#
# The backend serves the UI from frontend/dist/, which is gitignored and built
# on the server. A `git pull` alone updates the source but NOT dist/, so the
# old UI keeps being served until `npm run build` runs. This script closes that
# gap.
#
# Usage:
#   bin/deploy.sh
#
# Override the service name if yours differs from "cadence":
#   CADENCE_SERVICE=my-service bin/deploy.sh
#
# Skip the restart (e.g. to inspect the build first):
#   CADENCE_SKIP_RESTART=1 bin/deploy.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="${CADENCE_SERVICE:-cadence}"

cd "$REPO_ROOT"

echo "==> Pulling latest code"
git pull

echo "==> Installing frontend dependencies"
cd "$REPO_ROOT/frontend"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

echo "==> Building frontend (regenerating frontend/dist/)"
npm run build

cd "$REPO_ROOT"

if [ "${CADENCE_SKIP_RESTART:-0}" = "1" ]; then
  echo "==> CADENCE_SKIP_RESTART set — skipping backend restart"
  echo "    Restart manually when ready: systemctl restart $SERVICE"
else
  echo "==> Restarting backend ($SERVICE)"
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl restart "$SERVICE"
  else
    echo "warning: systemctl not found — restart the backend manually" >&2
  fi
fi

echo "==> Deploy complete. The backend is now serving the freshly built UI."
