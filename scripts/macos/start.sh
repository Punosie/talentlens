#!/usr/bin/env bash
# Start TalentLens (if it isn't running yet) and open it in the browser.
# Used by the TalentLens app in ~/Applications. Safe to run any number of times.
#   bash scripts/macos/start.sh [--no-browser]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Apps launched from Finder get a minimal PATH; add Homebrew and uv's locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

env_value() { # read a value from .env if present (never written by TalentLens); always succeeds
  if [[ -f "$ROOT/.env" ]]; then
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ROOT/.env" | tail -1 | tr -d '"\r'
  fi
  return 0
}
PORT="$(env_value TALENTLENS_PORT)"; PORT="${PORT:-8765}"
URL="http://127.0.0.1:$PORT"
LOGS="$HOME/Library/Logs/TalentLens"

up() { curl -fsS --max-time 2 "$URL/api/health" >/dev/null 2>&1; }

if ! up; then
  if [[ "$(env_value TALENTLENS_LLM)" != "off" ]] && command -v ollama >/dev/null 2>&1; then
    if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
      brew services start ollama >/dev/null 2>&1 || (nohup ollama serve >/dev/null 2>&1 &)
    fi
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "TalentLens needs 'uv', which was not found. Run: bash scripts/macos/setup.sh" >&2
    exit 1
  fi
  if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
    echo "The web UI has not been built yet. Run: bash scripts/macos/setup.sh" >&2
    exit 1
  fi
  mkdir -p "$LOGS"
  (cd "$ROOT" && nohup uv run --frozen talentlens >>"$LOGS/server.log" 2>&1 &)
  for _ in $(seq 1 170); do
    up && break
    sleep 0.7
  done
  if ! up; then
    echo "TalentLens did not start within 2 minutes. See the log: $LOGS/server.log" >&2
    exit 1
  fi
fi

[[ "${1:-}" == "--no-browser" ]] || open "$URL"
