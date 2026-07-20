#!/usr/bin/env bash
# Start the portal dev servers (FastAPI backend + Vite frontend) and keep them
# running in THIS terminal. Ctrl+C stops both.
#   usage:  bash portal/dev.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"        # portal/
ROOT="$(cd "$HERE/.." && pwd)"                # regulation-extract/
VENV="$ROOT/.venv/bin"

trap 'kill 0' INT TERM EXIT

echo ">> backend (FastAPI) on http://localhost:8001"
( "$VENV/uvicorn" backend.main:app --app-dir "$HERE" --port 8001 --reload ) &

echo ">> frontend (Vite)  on http://localhost:5173"
( npm --prefix "$HERE/frontend" run dev ) &

wait
