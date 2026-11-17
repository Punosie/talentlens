#!/usr/bin/env bash
# One-click update, started by TalentLens itself. Stops the server, pulls the new version,
# installs dependencies, builds the UI aside and swaps it in, then starts TalentLens again.
# On any failure the code goes back to the previous commit and the previous version restarts.
#   bash scripts/macos/update.sh --port 8765 --status <file> --branch main
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

PORT=8765
STATUS="$HOME/Library/Application Support/TalentLens/update/status.json"
BRANCH=main
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    *) shift ;;
  esac
done
mkdir -p "$(dirname "$STATUS")"

FROM=""; TO=""
if [[ -f "$STATUS" ]]; then
  FROM="$(sed -n 's/.*"from": *"\([^"]*\)".*/\1/p' "$STATUS" | head -1)"
  TO="$(sed -n 's/.*"to": *"\([^"]*\)".*/\1/p' "$STATUS" | head -1)"
fi

set_status() { # state message
  local msg="${2//\"/\'}"
  printf '{"state": "%s", "message": "%s", "from": "%s", "to": "%s", "at": "%s"}\n' \
    "$1" "$msg" "$FROM" "$TO" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS"
  echo "[$(date +%H:%M:%S)] $1 - $2"
}

OLD=""
fail() {
  local msg="$1"
  echo "Update failed: $msg"
  if [[ -n "$OLD" && "$(git rev-parse HEAD)" != "$OLD" ]]; then
    git reset --keep "$OLD" >/dev/null 2>&1 || true   # back to the version that worked
    uv sync --frozen >/dev/null 2>&1 || true
  fi
  set_status failed "$msg"
  bash "$ROOT/scripts/macos/start.sh" --no-browser || true
  exit 1
}

set_status updating "Stopping TalentLens"
sleep 1  # let the "update started" reply reach the browser
bash "$ROOT/scripts/macos/stop.sh" >/dev/null 2>&1 || true
for _ in $(seq 1 60); do
  lsof -ti "tcp:$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
  sleep 0.5
done
lsof -ti "tcp:$PORT" -sTCP:LISTEN >/dev/null 2>&1 && fail "TalentLens did not stop"

OLD="$(git rev-parse HEAD)"
set_status updating "Downloading the new version"
git fetch --quiet origin "$BRANCH" || fail "git fetch failed"
git merge --ff-only "origin/$BRANCH" || fail "git merge failed"

set_status updating "Installing components"
uv sync --frozen || fail "uv sync failed"

# Installs updated in-app never ran the install-time speed test. Measures only when needed;
# a failure never stops the update.
set_status updating "Checking CPU and GPU speed"
uv run --frozen talentlens benchmark --if-needed || echo "Benchmark skipped"

set_status updating "Building the screens"
(
  cd frontend || exit 1
  npm ci --no-audit --no-fund || exit 1
  rm -rf dist-next
  npm run build -- --outDir dist-next --emptyOutDir || exit 1
  [[ -f dist-next/index.html ]] || exit 1
  rm -rf dist-old
  [[ -d dist ]] && mv dist dist-old
  mv dist-next dist
  rm -rf dist-old
) || fail "building the screens failed"

set_status done "Updated to $TO"
bash "$ROOT/scripts/macos/start.sh" --no-browser
