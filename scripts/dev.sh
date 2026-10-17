#!/usr/bin/env bash
# Runs backend (8000), portal (8100) and frontend (3000, if present). Ctrl-C stops all.
set -u
PY=${PY:-python}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' INT TERM EXIT
(cd "$ROOT/backend" && $PY -m uvicorn app.main:app --reload --port 8000) &
(cd "$ROOT/portal" && $PY -m uvicorn main:app --reload --port 8100) &
if [ -f "$ROOT/frontend/package.json" ]; then (cd "$ROOT/frontend" && npm run dev) & fi
wait
