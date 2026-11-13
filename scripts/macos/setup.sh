#!/usr/bin/env bash
# TalentLens one-time (and repeatable) setup for macOS.
#
#   bash scripts/macos/setup.sh                  # recommended
#   bash scripts/macos/setup.sh --cv-dir ~/Desktop/CVs
#
# Options:
#   --cv-dir PATH       remember this resume folder (you can also choose it in the app)
#   --no-ai             skip the local AI (Ollama); everything else still works
#   --with-libreoffice  install LibreOffice so old .doc files can be read
#   --skip-tests        don't download the test browser (Playwright Chromium)
#   --no-app            don't create the TalentLens app in ~/Applications
#
# Safe to run again at any time. It never changes your resumes or a .env file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
MODEL="qwen2.5:3b-instruct"
CV_DIR="" NO_AI=0 WITH_LO=0 SKIP_TESTS=0 NO_APP=0 INVITE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cv-dir) CV_DIR="${2:?--cv-dir needs a path}"; shift 2 ;;
    --no-ai) NO_AI=1; shift ;;
    --with-libreoffice) WITH_LO=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    --no-app) NO_APP=1; shift ;;
    --invite) INVITE="${2:?--invite needs the invite link}"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok() { printf '    \033[32m%s\033[0m\n' "$1"; }
warn() { printf '    \033[33m%s\033[0m\n' "$1"; }

# --- 1. tools ------------------------------------------------------------------
step "Checking tools"
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [[ -x "$b" ]] && eval "$("$b" shellenv)" && break
  done
fi
if ! command -v brew >/dev/null 2>&1; then
  cat <<'EOF'
    TalentLens uses Homebrew (the standard Mac package manager) to install its tools.
    Install it by pasting this line into Terminal, then run this setup again:

      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

EOF
  exit 1
fi
ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"
[[ "$(uname -m)" == "arm64" ]] || warn "Intel Mac detected: everything works, but smart reading (AI) will be slower."

for tool in uv node; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "    Installing $tool ..."
    brew install "$tool" >/dev/null
  fi
done
ok "uv $(uv --version | awk '{print $2}') · node $(node --version)"

if [[ $NO_AI -eq 0 ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "    Installing Ollama (local AI runtime) ..."
    brew install ollama >/dev/null
  fi
  ok "ollama $(ollama --version 2>/dev/null | awk '{print $NF}')"
fi
if [[ $WITH_LO -eq 1 && ! -d "/Applications/LibreOffice.app" ]]; then
  echo "    Installing LibreOffice ..."
  brew install --cask libreoffice >/dev/null
fi

# --- 2. backend ----------------------------------------------------------------
step "Installing the backend (Python 3.12 via uv)"
uv sync --frozen
ok "Python dependencies installed"

# --- 3. preferences (saved in the app's settings.json; .env is never written) ----
step "Preferences"
if [[ -n "$CV_DIR" ]]; then
  mkdir -p "$CV_DIR"
  uv run --frozen talentlens set-folder "$CV_DIR"
else
  ok "Resume folder: you'll choose it in the app the first time it opens."
fi
[[ $NO_AI -eq 1 ]] && uv run --frozen talentlens set-ai off
[[ -n "$INVITE" ]] && { uv run --frozen talentlens join "$INVITE" || warn "Could not use the invite link; paste it later in Settings."; }

# --- 4. web UI -------------------------------------------------------------------
step "Building the web UI"
(cd frontend && npm ci --no-audit --no-fund && npm run build)
ok "UI built"

# --- 5. local AI model -------------------------------------------------------------
if [[ $NO_AI -eq 0 ]]; then
  step "Downloading the local AI model ($MODEL, about 2 GB, first time only)"
  # run Ollama in the background now and at every login
  brew services start ollama >/dev/null 2>&1 || (nohup ollama serve >/dev/null 2>&1 &)
  for _ in $(seq 1 30); do
    curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
  done
  ollama pull "$MODEL"
  ok "$MODEL ready"
fi
step "Measuring this computer's speed (picks the faster settings)"
uv run --frozen talentlens benchmark

step "Downloading search and OCR models (about 300 MB, first time only)"
uv run --frozen python -m talentlens.warmup

# --- 6. test browser (optional) -------------------------------------------------------
if [[ $SKIP_TESTS -eq 0 ]]; then
  step "Installing the test browser (Playwright Chromium)"
  (cd frontend && npx playwright install chromium)
fi

# --- 7. app in ~/Applications ------------------------------------------------------------
if [[ $NO_APP -eq 0 ]]; then
  step "Creating the TalentLens app"
  bash "$ROOT/scripts/macos/make_app.sh"
fi

printf '\n\033[1;32mTalentLens is ready.\033[0m Open it from Launchpad or Spotlight (search "TalentLens"),\n'
printf 'or run: bash scripts/macos/start.sh\n'
