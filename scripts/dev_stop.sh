#!/usr/bin/env bash
# Stops the local backend and frontend started by dev_start.sh (the local database keeps running; data is kept).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for name in backend frontend; do
  f="$ROOT/.localdb/logs/$name.pid"
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null && echo "stopped $name"; rm -f "$f"
done
for port in 8000 5173; do pid=$(lsof -ti tcp:$port -sTCP:LISTEN); [ -n "$pid" ] && kill $pid; done
# Wait (up to 20 s) until both ports are really free, so a start right after this never finds them busy.
for _ in $(seq 1 40); do
  lsof -ti tcp:8000 -sTCP:LISTEN >/dev/null || lsof -ti tcp:5173 -sTCP:LISTEN >/dev/null || break; sleep 0.5
done
exit 0
