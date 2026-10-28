#!/usr/bin/env bash
# Starts everything for LOCAL development: database, backend (port 8000), frontend (port 5173).
#   scripts/dev_start.sh            keep existing local data
#   scripts/dev_start.sh --fresh    wipe and reload SAMPLE data
# Stop with: scripts/dev_stop.sh      Logs: .localdb/logs/
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/.localdb/logs"; mkdir -p "$LOGS"
PORT_DB=54329
DEV_SECRET="local-dev-only-secret-not-for-production"   # local only; never used anywhere real

"$ROOT/scripts/local_db.sh" start >/dev/null
if [ "${1:-}" = "--fresh" ] || ! psql -h localhost -p $PORT_DB -U postgres -d finance_dev -c "select 1" >/dev/null 2>&1; then
  echo "Loading fresh SAMPLE data…"
  "$ROOT/scripts/local_db.sh" reset >/dev/null
  psql -h localhost -p $PORT_DB -U postgres -d finance_dev -q -f "$ROOT/db/local/dev_seed.sql"
  FRESH=1
fi

for port in 8000 5173; do
  if lsof -ti tcp:$port -sTCP:LISTEN >/dev/null; then echo "Port $port is busy — run scripts/dev_stop.sh first"; exit 1; fi
done

cd "$ROOT/backend"
ENVIRONMENT=development DATABASE_URL="host=localhost port=$PORT_DB user=postgres dbname=finance_dev" DB_SET_ROLE=app_api \
SUPABASE_URL=http://localhost:54321 SUPABASE_JWT_SECRET="$DEV_SECRET" SUPABASE_SERVICE_ROLE_KEY=unused-local \
CORS_ORIGINS='["http://localhost:5173"]' nohup .venv/bin/uvicorn app.main:app --port 8000 > "$LOGS/backend.log" 2>&1 &
echo $! > "$LOGS/backend.pid"

cd "$ROOT/frontend"
VITE_SUPABASE_URL=http://localhost:54321 VITE_SUPABASE_ANON_KEY=local-dev VITE_API_URL=http://localhost:8000 \
nohup ./node_modules/.bin/vite --port 5173 --strictPort > "$LOGS/frontend.log" 2>&1 &
echo $! > "$LOGS/frontend.pid"

for _ in $(seq 1 60); do
  curl -sf http://localhost:8000/api/health >/dev/null && curl -sf http://localhost:5173 >/dev/null && break; sleep 0.5
done
curl -sf http://localhost:8000/api/health >/dev/null || { echo "Backend did not start — see $LOGS/backend.log"; exit 1; }
if [ "${FRESH:-}" = 1 ]; then
  "$ROOT/backend/.venv/bin/python" "$ROOT/e2e/sample_activity.py" >/dev/null && echo "Added SAMPLE bills, receipts and expenses"
fi
echo "Running:  app http://localhost:5173   ·   API http://localhost:8000/api/docs"
echo "Open it signed in:  backend/.venv/bin/python scripts/dev_open.py owner|accountant|operator"
