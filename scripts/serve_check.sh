#!/usr/bin/env bash
# Check that the OTA static server is reachable locally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

load_config

PORT="${OTA_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"

if [[ -n "${OTA_ACCESS_TOKEN:-}" ]]; then
  URL="${URL}?token=${OTA_ACCESS_TOKEN}"
fi

if curl -sf --max-time 3 "$URL" >/dev/null 2>&1; then
  log "OTA server reachable at $URL"
  exit "$EC_SUCCESS"
fi

# Fallback: Python server may be running
if lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  log "Port $PORT is listening (server may be starting)"
  exit "$EC_SUCCESS"
fi

log_error "OTA server not reachable at $URL"
log "Start the server:"
log "  $OTA_BUILDER_ROOT/server/start_server.sh"
log "Or install nginx: brew install nginx && $OTA_BUILDER_ROOT/server/start_nginx.sh"
exit "$EC_PUBLISH"
