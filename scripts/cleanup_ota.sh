#!/usr/bin/env bash
# Remove old builds (retention policy) then regenerate index cache.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

if [[ ! -f "$ROOT/config/projects.json" ]]; then
  echo "Missing config/projects.json" >&2
  exit 1
fi

BASE_URL="${OTA_BASE_URL%/}"

python3 "$ROOT/tools/cleanup_builds.py" \
  --ota-dir "$OTA_BUILDS_DIR" \
  --keep "${OTA_KEEP_BUILDS:-5}" \
  --max-age-days "${OTA_MAX_AGE_DAYS:-7}"

python3 "$ROOT/tools/generate_indexes.py" \
  --ota-dir "$OTA_BUILDS_DIR" \
  --projects-json "$ROOT/config/projects.json" \
  --base-url "$BASE_URL" \
  --access-token "${OTA_ACCESS_TOKEN:-}"
