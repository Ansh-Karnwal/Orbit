#!/usr/bin/env bash
# Starts the portal, runs portal-marked e2e tests, stops the portal.
set -u
PY=${PY:-python}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/portal" && $PY -m uvicorn main:app --port 8100) &
PORTAL_PID=$!
trap 'kill $PORTAL_PID 2>/dev/null' EXIT
sleep 2
cd "$ROOT/backend" && $PY -m pytest -q -m portal
