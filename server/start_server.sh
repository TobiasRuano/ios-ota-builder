#!/usr/bin/env bash
# Lightweight Python static server fallback (correct MIME types for OTA).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

mkdir -p "$OTA_BUILDS_DIR"

export OTA_BUILDS_DIR OTA_PORT OTA_ACCESS_TOKEN OTA_BASE_URL
export OTA_PROJECTS_JSON="$ROOT/config/projects.json"
exec python3 "$ROOT/server/static_server.py"
