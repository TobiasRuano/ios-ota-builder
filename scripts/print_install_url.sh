#!/usr/bin/env bash
# Print the latest install URL for a project (includes access token).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

USE_STABLE_URL=false
PROJECT_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest)
      USE_STABLE_URL=true
      shift
      ;;
    -h | --help)
      cat >&2 <<EOF
Usage: print_install_url.sh [--latest] <project-id>

Options:
  --latest  Print stable redirect URL (/latest/<project-id>) instead of
            resolving the newest build folder on disk.

Examples:
  print_install_url.sh my-app
  print_install_url.sh --latest my-app
EOF
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$PROJECT_ID" ]]; then
        PROJECT_ID="$1"
      else
        echo "Unexpected argument: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

PROJECT_ID="${PROJECT_ID:-dev-quotes}"

if [[ -z "${OTA_ACCESS_TOKEN:-}" ]]; then
  echo "Error: no access token. Run: $ROOT/scripts/generate_access_token.sh" >&2
  exit 1
fi

BASE="${OTA_BASE_URL%/}"

if [[ "$USE_STABLE_URL" == "true" ]]; then
  python3 - "$ROOT" "$PROJECT_ID" <<'PY'
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
project_id = sys.argv[2]
projects_json = root / "config" / "projects.json"
ota_builds = Path(os.environ["OTA_BUILDS_DIR"])

projects = {}
if projects_json.is_file():
    projects = json.loads(projects_json.read_text(encoding="utf-8")).get("projects", {})
    if project_id not in projects:
        sys.exit(2)

sys.path.insert(0, str(root / "tools"))
from ota_index import find_latest_build

if find_latest_build(ota_builds, project_id, projects_config=projects or None) is None:
    sys.exit(1)
PY
  rc=$?
  if [[ $rc -eq 2 ]]; then
    echo "Unknown project: $PROJECT_ID" >&2
    exit 1
  fi
  if [[ $rc -ne 0 ]]; then
    echo "No successful builds for project: $PROJECT_ID" >&2
    exit 1
  fi
  echo "${BASE}/latest/${PROJECT_ID}?token=${OTA_ACCESS_TOKEN}"
  exit 0
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
URL="${BASE}/${PROJECT_ID}/${BUILD_DIR}/install.html?token=${OTA_ACCESS_TOKEN}"

echo "$URL"
