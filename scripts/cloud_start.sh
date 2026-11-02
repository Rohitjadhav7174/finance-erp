#!/usr/bin/env bash
# Runs the app on your Mac against your REAL Supabase project: real email + password sign-in, real data.
#   scripts/cloud_start.sh        then open http://localhost:5173
# Needs backend/.env.cloud and frontend/.env.cloud.local filled in (both git-ignored).
# Stop with: scripts/dev_stop.sh      Logs: .localdb/logs/
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/.localdb/logs"; mkdir -p "$LOGS"

for f in backend/.env.cloud frontend/.env.cloud.local; do
  [ -f "$ROOT/$f" ] || { echo "Missing $f"; exit 1; }
  # Only real settings lines count, not the explanatory comments.
  if grep -v '^[[:space:]]*#' "$ROOT/$f" | grep -q "PASTE_"; then
    echo "Fill in the PASTE_ values in $f first:"; grep -v '^[[:space:]]*#' "$ROOT/$f" | grep "PASTE_" | cut -d= -f1; exit 1
  fi
done
for port in 8000 5173; do
  if lsof -ti tcp:$port -sTCP:LISTEN >/dev/null; then echo "Port $port is busy — run scripts/dev_stop.sh first"; exit 1; fi
done

cd "$ROOT/backend"
( set -a; source "$ROOT/backend/.env.cloud"; set +a
  nohup .venv/bin/uvicorn app.main:app --port 8000 > "$LOGS/backend.log" 2>&1 & echo $! > "$LOGS/backend.pid" )

cd "$ROOT/frontend"
nohup ./node_modules/.bin/vite --mode cloud --port 5173 --strictPort > "$LOGS/frontend.log" 2>&1 &
echo $! > "$LOGS/frontend.pid"

for _ in $(seq 1 60); do
  curl -sf http://localhost:8000/api/health >/dev/null && curl -sf http://localhost:5173 >/dev/null && break; sleep 0.5
done
curl -sf http://localhost:8000/api/health >/dev/null || { echo "Backend did not start — see $LOGS/backend.log"; exit 1; }
echo "Running against Supabase:  http://localhost:5173  (sign in with your email and password)"
open http://localhost:5173/login 2>/dev/null || true
