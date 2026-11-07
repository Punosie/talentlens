#!/usr/bin/env bash
# Stop the TalentLens server. Ollama is left running because other apps may use it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT=8765
if [[ -f "$ROOT/.env" ]]; then
  p="$(sed -n 's/^[[:space:]]*TALENTLENS_PORT[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$ROOT/.env" | tail -1)"
  PORT="${p:-$PORT}"
fi
PIDS="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -z "$PIDS" ]]; then
  echo "TalentLens is not running (nothing listening on port $PORT)."
  exit 0
fi
echo "Stopping TalentLens (PID $PIDS) on port $PORT"
kill $PIDS
echo "TalentLens stopped."
