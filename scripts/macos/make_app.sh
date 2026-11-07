#!/usr/bin/env bash
# Build ~/Applications/TalentLens.app: a tiny AppleScript app that runs start.sh.
# It appears in Launchpad and Spotlight; drag it to the Dock to keep it there.
# Built locally, so macOS doesn't quarantine it (no "unidentified developer" prompt).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPS="$HOME/Applications"
APP="$APPS/TalentLens.app"
START="$ROOT/scripts/macos/start.sh"
mkdir -p "$APPS"
rm -rf "$APP"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SCRIPT="$TMP/TalentLens.applescript"
cat >"$SCRIPT" <<EOF
set startScript to "$START"
try
	do shell script "/bin/bash " & quoted form of startScript
on error errMsg
	display dialog "TalentLens could not start." & return & return & errMsg buttons {"OK"} default button "OK" with icon stop with title "TalentLens"
end try
EOF
osacompile -o "$APP" "$SCRIPT"

cp "$ROOT/assets/TalentLens.icns" "$APP/Contents/Resources/applet.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleName TalentLens" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.punosie.talentlens" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.punosie.talentlens" "$APP/Contents/Info.plist"
touch "$APP"  # refresh the icon cache

echo "    Created $APP"
echo "    Tip: open it once, then right-click its Dock icon → Options → Keep in Dock."
