#!/usr/bin/env bash
# Run a dashboard-triggered OTA build job.
# Usage: run_build_job.sh <job-id>

set -euo pipefail

JOB_ID="${1:-}"
if [[ -z "$JOB_ID" ]]; then
  echo "Usage: run_build_job.sh <job-id>" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

JOBS_DIR="$OTA_BUILDER_ROOT/.server/build-jobs"
JOB_FILE="$JOBS_DIR/${JOB_ID}.json"
LOG_FILE="$JOBS_DIR/${JOB_ID}.log"

mkdir -p "$JOBS_DIR"
exec >>"$LOG_FILE" 2>&1

update_job() {
  local status="$1"
  local extra_json="${2:-}"
  python3 - "$JOB_FILE" "$status" "$extra_json" <<'PY'
import json, sys
from datetime import datetime, timezone

path, status, extra_raw = sys.argv[1:4]
extra = json.loads(extra_raw) if extra_raw else {}
with open(path, encoding="utf-8") as f:
    job = json.load(f)
job["status"] = status
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
if status in ("preparing", "building") and not job.get("started_at"):
    job["started_at"] = now
if status in ("success", "failed"):
    job["finished_at"] = now
job.update(extra)
with open(path, "w", encoding="utf-8") as f:
    json.dump(job, f, indent=2)
    f.write("\n")
PY
}

if [[ ! -f "$JOB_FILE" ]]; then
  log_error "Job file not found: $JOB_FILE"
  exit 1
fi

PROJECT_ID="$(jq -r '.project_id' "$JOB_FILE")"
BRANCH="$(jq -r '.branch // ""' "$JOB_FILE")"
GIT_MODE="$(jq -r '.git_mode // "auto"' "$JOB_FILE")"
CONFIGURATION="$(jq -r '.configuration // ""' "$JOB_FILE")"

log "=== Build job $JOB_ID for $PROJECT_ID ==="

load_config

update_job "preparing"

WORKSPACE_PATH=""
if ! WORKSPACE_PATH="$("$OTA_BUILDER_ROOT/scripts/prepare_git_workspace.sh" \
  "$PROJECT_ID" "$BRANCH" "$GIT_MODE")"; then
  update_job "failed" '{"error":"git workspace preparation failed"}'
  exit 1
fi

update_job "building" "$(WORKSPACE_PATH="$WORKSPACE_PATH" python3 -c 'import json,os; print(json.dumps({"workspace_path": os.environ["WORKSPACE_PATH"]}))')"

BUILD_ARGS=("$OTA_BUILDER_ROOT/agent_build_ota.sh" "--workspace-path" "$WORKSPACE_PATH")
if [[ -n "$CONFIGURATION" ]]; then
  if [[ "$CONFIGURATION" == "Debug" ]]; then
    BUILD_ARGS+=(--debug)
  elif [[ "$CONFIGURATION" == "Release" ]]; then
    BUILD_ARGS+=(--release)
  fi
fi
BUILD_ARGS+=("$PROJECT_ID")

set +e
"${BUILD_ARGS[@]}"
EC=$?
set -e

if [[ $EC -eq 0 ]]; then
  BUILD_DIR=""
  if [[ -d "$OTA_BUILDS_DIR/$PROJECT_ID" ]]; then
    BUILD_DIR="$(ls -1t "$OTA_BUILDS_DIR/$PROJECT_ID" 2>/dev/null | head -1 || true)"
  fi
  update_job "success" "$(BUILD_DIR="$BUILD_DIR" python3 -c 'import json,os; print(json.dumps({"build_dir": os.environ.get("BUILD_DIR",""), "error": ""}))')"
  log "=== Build job $JOB_ID succeeded ==="
  exit 0
fi

update_job "failed" "$(EC=$EC python3 -c 'import json,os; print(json.dumps({"error": "build exited with code " + os.environ["EC"]}))')"
log "=== Build job $JOB_ID failed (exit $EC) ==="
exit "$EC"
