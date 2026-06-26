#!/usr/bin/env bash
# Print the latest install URL for a project (includes access token).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

PROJECT_ID="${1:-dev-quotes}"

if [[ -z "${OTA_ACCESS_TOKEN:-}" ]]; then
  echo "Error: no access token. Run: $ROOT/scripts/generate_access_token.sh" >&2
  exit 1
fi

LATEST=""
LATEST_MTIME=0
for summary in "$OTA_BUILDS_DIR/$PROJECT_ID"/*/summary.json; do
  [[ -f "$summary" ]] || continue
  status="$(jq -r '.status // ""' "$summary")"
  [[ "$status" == "success" ]] || continue
  mtime="$(stat -f %m "$summary" 2>/dev/null || stat -c %Y "$summary")"
  if [[ "$mtime" -gt "$LATEST_MTIME" ]]; then
    LATEST_MTIME=$mtime
    LATEST="$summary"
  fi
done

if [[ -z "$LATEST" ]]; then
  echo "No successful builds for project: $PROJECT_ID" >&2
  exit 1
fi

BUILD_DIR="$(jq -r '.build_dir' "$LATEST")"
BASE="${OTA_BASE_URL%/}"
URL="${BASE}/${PROJECT_ID}/${BUILD_DIR}/install.html?token=${OTA_ACCESS_TOKEN}"

echo "$URL"
