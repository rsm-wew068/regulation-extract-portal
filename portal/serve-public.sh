#!/usr/bin/env bash
# Expose the portal backend publicly via Cloudflare Tunnel so the Vercel
# frontend can reach it. KEEP THIS TERMINAL OPEN while you want the portal live.
#
#   usage:  bash portal/serve-public.sh
#   stop:   Ctrl+C
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"          # portal/
ROOT="$(cd "$HERE/.." && pwd)"                  # regulation-extract/
VENV="$ROOT/.venv/bin"
CF=/opt/homebrew/bin/cloudflared

echo ">> backend on http://localhost:8001"
"$VENV/uvicorn" backend.main:app --app-dir "$HERE" --port 8001 &
BE=$!

echo ">> Cloudflare tunnel starting…"
rm -f /tmp/cf.log
"$CF" tunnel --url http://localhost:8001 > /tmp/cf.log 2>&1 &
CFP=$!

URL=""
for _ in $(seq 1 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/cf.log 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
echo
echo "=========================================================="
echo "  Public backend URL:  ${URL:-(did not come up — see /tmp/cf.log)}"
echo "  Paste this URL here so Claude can wire it into Vercel."
echo "  Ctrl+C stops both. (URL changes each restart.)"
echo "=========================================================="

trap 'kill $BE $CFP 2>/dev/null' INT TERM EXIT
wait
