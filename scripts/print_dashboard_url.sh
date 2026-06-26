#!/usr/bin/env bash
# Print the OTA dashboard URL (lists all projects and builds).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

if [[ -z "${OTA_ACCESS_TOKEN:-}" ]]; then
  echo "Error: no access token. Run: $ROOT/scripts/setup.sh" >&2
  exit 1
fi

BASE="${OTA_BASE_URL%/}"
echo "${BASE}/?token=${OTA_ACCESS_TOKEN}"
