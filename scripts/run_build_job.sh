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
SYNC_STRATEGY="$(jq -r '.sync_strategy // ""' "$JOB_FILE")"
SYNC_BEFORE_BUILD="$(jq -r '.sync_before_build // true' "$JOB_FILE")"
ALLOW_STALE_BUILD="$(jq -r '.allow_stale_build // false' "$JOB_FILE")"
if [[ -z "$SYNC_STRATEGY" || "$SYNC_STRATEGY" == "null" ]]; then
  SYNC_STRATEGY="match_remote"
fi

log "=== Build job $JOB_ID for $PROJECT_ID ==="

load_config

update_job "preparing"

echo "[stage] git_sync"

PREPARE_ARGS=(
  "$OTA_BUILDER_ROOT/scripts/prepare_git_workspace.sh"
  "--strategy" "${SYNC_STRATEGY:-match_remote}"
)
if [[ "$SYNC_BEFORE_BUILD" == "true" ]]; then
  PREPARE_ARGS+=("--verify-in-sync")
elif [[ "$ALLOW_STALE_BUILD" != "true" ]]; then
  PREPARE_ARGS+=("--verify-in-sync")
fi
PREPARE_ARGS+=("$PROJECT_ID" "$BRANCH" "$GIT_MODE")

WORKSPACE_PATH=""
if ! WORKSPACE_PATH="$("${PREPARE_ARGS[@]}")"; then
  update_job "failed" '{"error":"git workspace sync failed — see job log for details","stage":"git_sync"}'
  exit 1
fi

WORKSPACE_COMMIT="$(git -C "$WORKSPACE_PATH" rev-parse HEAD 2>/dev/null || echo "")"
WORKSPACE_COMMIT_SHORT="$(git -C "$WORKSPACE_PATH" rev-parse --short HEAD 2>/dev/null || echo "")"
REMOTE_NAME="$(jq -r --arg id "$PROJECT_ID" '.projects[$id].git.remote // "origin"' "$OTA_BUILDER_ROOT/config/projects.json")"
EFFECTIVE_BRANCH="$BRANCH"
if [[ -z "$EFFECTIVE_BRANCH" ]]; then
  EFFECTIVE_BRANCH="$(git -C "$WORKSPACE_PATH" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
fi
REMOTE_COMMIT=""
if [[ -n "$EFFECTIVE_BRANCH" ]] && git -C "$WORKSPACE_PATH" show-ref --verify --quiet "refs/remotes/${REMOTE_NAME}/${EFFECTIVE_BRANCH}"; then
  REMOTE_COMMIT="$(git -C "$WORKSPACE_PATH" rev-parse "${REMOTE_NAME}/${EFFECTIVE_BRANCH}")"
fi

update_job "building" "$(python3 -c 'import json,os; print(json.dumps({
  "workspace_path": os.environ["WORKSPACE_PATH"],
  "workspace_commit": os.environ.get("WORKSPACE_COMMIT", ""),
  "workspace_commit_short": os.environ.get("WORKSPACE_COMMIT_SHORT", ""),
  "remote_commit": os.environ.get("REMOTE_COMMIT", ""),
  "sync_strategy": os.environ.get("SYNC_STRATEGY", ""),
  "sync_before_build": os.environ.get("SYNC_BEFORE_BUILD", "") == "true",
  "allow_stale_build": os.environ.get("ALLOW_STALE_BUILD", "") == "true",
}))' \
  WORKSPACE_PATH="$WORKSPACE_PATH" \
  WORKSPACE_COMMIT="$WORKSPACE_COMMIT" \
  WORKSPACE_COMMIT_SHORT="$WORKSPACE_COMMIT_SHORT" \
  REMOTE_COMMIT="$REMOTE_COMMIT" \
  SYNC_STRATEGY="$SYNC_STRATEGY" \
  SYNC_BEFORE_BUILD="$SYNC_BEFORE_BUILD" \
  ALLOW_STALE_BUILD="$ALLOW_STALE_BUILD")"

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

FAIL_STAGE=""
if [[ -f "$LOG_FILE" ]]; then
  FAIL_STAGE="$(grep -E '^\[stage\] ' "$LOG_FILE" 2>/dev/null | tail -1 | sed 's/^\[stage\] //' || true)"
fi
FAIL_ERROR="build exited with code $EC"
if [[ -n "$FAIL_STAGE" ]]; then
  FAIL_ERROR="build failed at ${FAIL_STAGE} (exit $EC)"
fi
update_job "failed" "$(FAIL_ERROR="$FAIL_ERROR" FAIL_STAGE="$FAIL_STAGE" python3 -c 'import json,os; print(json.dumps({"error": os.environ["FAIL_ERROR"], "stage": os.environ.get("FAIL_STAGE","")}))')"
log "=== Build job $JOB_ID failed (exit $EC) ==="
exit "$EC"
