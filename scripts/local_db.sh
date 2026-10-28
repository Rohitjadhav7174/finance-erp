#!/usr/bin/env bash
# Local throwaway Postgres for development/tests. Data lives in ./.localdb (gitignored).
# Usage: scripts/local_db.sh start|stop|reset
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/.localdb/data"
PORT="${LOCAL_PG_PORT:-54329}"
DB="${LOCAL_PG_DB:-finance_dev}"

start() {
  if [ ! -d "$DATA" ]; then
    mkdir -p "$ROOT/.localdb"
    initdb -D "$DATA" -U postgres --auth=trust >/dev/null
  fi
  pg_ctl -D "$DATA" -o "-p $PORT -k $ROOT/.localdb -c listen_addresses=localhost" -l "$ROOT/.localdb/pg.log" status >/dev/null 2>&1 \
    || pg_ctl -D "$DATA" -o "-p $PORT -k $ROOT/.localdb -c listen_addresses=localhost" -l "$ROOT/.localdb/pg.log" -w start >/dev/null
  echo "postgres running on localhost:$PORT"
}

reset() {
  start
  psql -h localhost -p "$PORT" -U postgres -q -d postgres \
    -c "select pg_terminate_backend(pid) from pg_stat_activity where datname = '$DB' and pid <> pg_backend_pid()" >/dev/null
  psql -h localhost -p "$PORT" -U postgres -q -c "drop database if exists $DB" -c "create database $DB"
  psql -h localhost -p "$PORT" -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f "$ROOT/db/local/supabase_shim.sql"
  for f in "$ROOT"/supabase/migrations/*.sql; do
    psql -h localhost -p "$PORT" -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f "$f"
    echo "applied $(basename "$f")"
  done
}

case "${1:-start}" in
  start) start ;;
  stop) pg_ctl -D "$DATA" stop ;;
  reset) reset ;;
  *) echo "usage: $0 start|stop|reset"; exit 1 ;;
esac
