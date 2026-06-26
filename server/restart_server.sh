#!/usr/bin/env bash
# Restart the OTA static server via launchd.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

PREFIX="${LAUNCHD_LABEL_PREFIX:-com.local.ios-ota-builder}"
PLIST="$HOME/Library/LaunchAgents/${PREFIX}.ota-server.plist"

if [[ ! -f "$PLIST" ]]; then
  "$ROOT/scripts/install_launchagents.sh"
fi

launchctl bootout "gui/$(id -u)/${PREFIX}.ota-server" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 2

PORT="${OTA_PORT:-8765}"
if [[ -n "${OTA_ACCESS_TOKEN:-}" ]]; then
  curl -sf "http://127.0.0.1:${PORT}/?token=${OTA_ACCESS_TOKEN}" >/dev/null
  echo "OTA server running on :${PORT} (auth enabled)"
else
  echo "Warning: OTA_ACCESS_TOKEN not set — run scripts/setup.sh" >&2
  exit 1
fi
