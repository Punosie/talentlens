#!/usr/bin/env bash
# Uninstall TalentLens from this Mac, and optionally Ollama and the tools setup installed.
#
#   bash scripts/macos/uninstall.sh            # asks before each optional part
#   bash scripts/macos/uninstall.sh --dry-run  # only shows what it would do
#   bash scripts/macos/uninstall.sh --all --yes
#
# Your resume folders (CVs, JDs) and every file in them are NEVER touched.
#
# Always removed (TalentLens itself): the running server, ~/Applications/TalentLens.app,
#   ~/Library/Application Support/TalentLens (libraries, settings, AI search models)
#   and ~/Library/Logs/TalentLens.
# Asked one by one (or all with --all): Ollama + its models (~/.ollama), the Playwright test
#   browser, uv-managed Python + caches, uv / Node.js / GitHub CLI / Git (Homebrew),
#   LibreOffice, Homebrew itself, and the TalentLens code folder.
#
# Options: --all  --yes  --keep-data (keep libraries/settings)  --dry-run
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
DATA="$HOME/Library/Application Support/TalentLens"
LOGS="$HOME/Library/Logs/TalentLens"
APP="$HOME/Applications/TalentLens.app"
ALL=0 YES=0 KEEP=0 DRY=0
for a in "$@"; do
  case "$a" in
    --all) ALL=1 ;; --yes|-y) YES=1 ;; --keep-data) KEEP=1 ;; --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
done_() { printf '    \033[32m%s\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

confirm() { # confirm "question" [default y|n]
  local def="${2:-n}"
  [[ $ALL -eq 1 ]] && return 0
  if [[ $YES -eq 1 ]]; then [[ "$def" == y ]]; return; fi
  local hint="[y/N]"; [[ "$def" == y ]] && hint="[Y/n]"
  local ans; read -r -p "    $1 $hint " ans </dev/tty || ans=""
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[Yy] ]]
}

run() { # run "description" cmd...
  local what="$1"; shift
  if [[ $DRY -eq 1 ]]; then info "[dry run] would: $what"; return 0; fi
  if "$@" >/dev/null 2>&1; then done_ "$what"; else printf '    \033[33mcould not %s\033[0m\n' "$what"; fi
}

remove_dir() { # remove_dir path label
  if [[ ! -e "$1" ]]; then info "$2 not found (already removed)"; return; fi
  local size; size="$(du -sh "$1" 2>/dev/null | cut -f1)"
  run "remove $2 ($1, $size)" rm -rf "$1"
}

brew_remove() { # brew_remove formula label [--cask]
  if ! have brew; then info "Homebrew not found; skipped $2"; return; fi
  if brew list ${3:-} "$1" >/dev/null 2>&1; then run "uninstall $2" brew uninstall ${3:-} "$1"
  else info "$2 is not installed via Homebrew (skipped)"; fi
}

# remember where the resumes are (never touched), to reassure at the end
RESUMES=()
if [[ -f "$DATA/settings.json" ]]; then
  d="$(sed -n 's/.*"cv_dir": *"\([^"]*\)".*/\1/p' "$DATA/settings.json" | head -1)"
  [[ -n "$d" ]] && RESUMES+=("$d")
fi
[[ -d "$HOME/Desktop/JDs" ]] && RESUMES+=("$HOME/Desktop/JDs")

printf '\033[1;36mTalentLens uninstaller\033[0m\n'
[[ $DRY -eq 1 ]] && printf '\033[33m(dry run: nothing will be changed)\033[0m\n'
info "Your resume folders and their files are never touched."

# --- 1. TalentLens itself -----------------------------------------------------------------
step "Stopping TalentLens"
PORT=8765
if [[ -f "$ROOT/.env" ]]; then
  p="$(sed -n 's/^[[:space:]]*TALENTLENS_PORT[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$ROOT/.env" | tail -1)"
  PORT="${p:-$PORT}"
fi
PIDS="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then run "stop the TalentLens server (PID $PIDS)" kill $PIDS; else info "not running"; fi

step "Removing the TalentLens app"
remove_dir "$APP" "TalentLens.app"

step "Removing TalentLens working data"
if [[ $KEEP -eq 1 ]]; then info "kept $DATA (--keep-data)"
else
  remove_dir "$DATA" "library databases, settings and AI search models"
  remove_dir "$LOGS" "logs"
fi

# --- 2. optional components -----------------------------------------------------------------
step "Ollama (local AI) and its models"
if have ollama || [[ -d "$HOME/.ollama" || -d /Applications/Ollama.app ]]; then
  if confirm "Remove Ollama and all its downloaded AI models? (other apps may use Ollama)"; then
    have brew && run "stop the Ollama background service" brew services stop ollama
    pkill -x ollama >/dev/null 2>&1 || true
    brew_remove ollama "Ollama"
    if [[ -d /Applications/Ollama.app ]]; then
      if have brew && brew list --cask ollama >/dev/null 2>&1; then brew_remove ollama "Ollama app" --cask
      else remove_dir /Applications/Ollama.app "Ollama app"; fi
    fi
    remove_dir "$HOME/.ollama" "Ollama models"
  else info "kept"; fi
else info "not installed"; fi

step "Test browser (Playwright Chromium)"
PW="$HOME/Library/Caches/ms-playwright"
if [[ -d "$PW" ]]; then
  if confirm "Remove the Playwright test browsers? (shared with other projects that use Playwright)" y; then
    remove_dir "$PW" "Playwright browsers"
  else info "kept"; fi
else info "not installed"; fi

step "uv-managed Python and caches"
if have uv && confirm "Remove uv-managed Python versions and uv caches?"; then
  run "remove uv-managed Python versions" uv python uninstall --all
  run "clean the uv cache" uv cache clean
else info "kept (or uv not installed)"; fi

step "Shared tools (uv, Node.js, GitHub CLI, Git)"
info "Other programs may need these. Only remove them if you installed them just for TalentLens."
for pair in "uv:uv" "node:Node.js" "gh:GitHub CLI" "git:Git (Homebrew copy; macOS keeps its own)"; do
  f="${pair%%:*}"; label="${pair#*:}"
  if confirm "Uninstall $label?"; then brew_remove "$f" "$label"; else info "kept $label"; fi
done

step "LibreOffice"
if [[ -d /Applications/LibreOffice.app ]]; then
  if confirm "Uninstall LibreOffice?"; then brew_remove libreoffice "LibreOffice" --cask; else info "kept"; fi
else info "not installed"; fi

step "Homebrew"
if have brew; then
  info "Homebrew manages many apps; removing it also removes everything installed with it."
  if [[ $ALL -eq 1 && $YES -eq 1 ]]; then
    info "skipped: --all never removes Homebrew; run without --yes to be asked"
  elif [[ $YES -eq 0 ]] && confirm "Uninstall Homebrew itself?"; then
    if [[ $DRY -eq 1 ]]; then info "[dry run] would: run the official Homebrew uninstaller"
    else /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)"; fi
  else info "kept"; fi
else info "not installed"; fi

step "TalentLens code folder"
if confirm "Delete the TalentLens code folder ($ROOT)?"; then
  case "$ROOT" in
    "$HOME"|"/"|"") info "refusing to delete $ROOT" ;;
    *) run "delete $ROOT" rm -rf "$ROOT" ;;
  esac
else info "kept $ROOT"; fi

echo
if [[ $DRY -eq 1 ]]; then printf '\033[32mDry run finished. Nothing was changed.\033[0m\n'
else printf '\033[32mTalentLens has been uninstalled.\033[0m\n'; fi
for d in "${RESUMES[@]+"${RESUMES[@]}"}"; do info "Your files are untouched: $d"; done
