#!/usr/bin/env bash
# Shared helpers for ios-ota-builder pipeline.

set -euo pipefail

# Exit codes (per spec)
export EC_SUCCESS=0
export EC_ENVIRONMENT=10
export EC_DEPENDENCIES=20
export EC_BUILD=30
export EC_ARCHIVE=40
export EC_EXPORT=50
export EC_PUBLISH=60
export EC_MANIFEST=70
export EC_INDEX=80

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

log_error() {
  log "ERROR: $*" >&2
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log_error "Required command not found: $cmd"
    exit "$EC_ENVIRONMENT"
  fi
}

load_config() {
  # shellcheck source=/dev/null
  source "$OTA_BUILDER_ROOT/config/env.sh"
  require_cmd jq
  require_cmd git
  require_cmd python3
  require_local_config
}

require_local_config() {
  local local_env="$OTA_BUILDER_ROOT/config/local.env"
  local missing=0
  if [[ ! -f "$local_env" ]]; then
    log_error "Missing config/local.env"
    log "Run: $OTA_BUILDER_ROOT/scripts/setup.sh"
    missing=1
  fi
  if [[ -z "${OTA_BASE_URL:-}" ]]; then
    log_error "OTA_BASE_URL is not set in config/local.env"
    missing=1
  fi
  if [[ -z "${OTA_ACCESS_TOKEN:-}" ]]; then
    log_error "OTA_ACCESS_TOKEN is not set in config/local.env"
    log "Run: $OTA_BUILDER_ROOT/scripts/setup.sh"
    missing=1
  fi
  if [[ -z "${APPLE_TEAM_ID:-}" ]]; then
    log_error "APPLE_TEAM_ID is not set in config/local.env"
    missing=1
  fi
  if [[ $missing -ne 0 ]]; then
    exit "$EC_ENVIRONMENT"
  fi
}

load_project() {
  local project_id="$1"
  local config_file="$OTA_BUILDER_ROOT/config/projects.json"

  if [[ ! -f "$config_file" ]]; then
    log_error "Missing config/projects.json"
    log "Copy the example: cp config/projects.json.example config/projects.json"
    log "Then edit paths, schemes, and bundle IDs for your apps."
    exit "$EC_ENVIRONMENT"
  fi

  if ! jq -e --arg id "$project_id" '.projects[$id]' "$config_file" >/dev/null 2>&1; then
    log_error "Unknown project-id: $project_id"
    if [[ "$project_id" == /* || "$project_id" == ./* || "$project_id" == ~* ]]; then
      log_error "You passed a filesystem path. Use project-id instead (not the repo path)."
      log "Example: agent_build_ota.sh dev-quotes"
      log "Not:     agent_build_ota.sh $project_id"
    fi
    local resolved hint=""
    if [[ "$project_id" == /* ]]; then
      resolved="$(cd "$project_id" 2>/dev/null && pwd || true)"
    fi
    if [[ -n "$resolved" ]]; then
      hint="$(jq -r --arg p "$resolved" '.projects | to_entries[] | select(.value.path == $p) | .key' "$config_file" 2>/dev/null | head -1)"
      if [[ -n "$hint" ]]; then
        log "Did you mean project-id: $hint ?"
      fi
    fi
    log "Registered project IDs:"
    jq -r '.projects | to_entries[] | "  \(.key)\t\(.value.display_name)\t\(.value.path)"' "$config_file" >&2
    exit "$EC_ENVIRONMENT"
  fi

  PROJECT_ID="$project_id"
  DISPLAY_NAME="$(jq -r --arg id "$project_id" '.projects[$id].display_name' "$config_file")"
  PROJECT_PATH="$(jq -r --arg id "$project_id" '.projects[$id].path' "$config_file")"
  XCODEPROJ="$(jq -r --arg id "$project_id" '.projects[$id].xcodeproj' "$config_file")"
  SCHEME="$(jq -r --arg id "$project_id" '.projects[$id].scheme' "$config_file")"
  CONFIGURATION="$(jq -r --arg id "$project_id" '.projects[$id].configuration' "$config_file")"
  BUNDLE_ID="$(jq -r --arg id "$project_id" '.projects[$id].bundle_id' "$config_file")"
  TEAM_ID="$(jq -r --arg id "$project_id" '.projects[$id].team_id // empty' "$config_file")"
  if [[ -z "$TEAM_ID" || "$TEAM_ID" == "null" ]]; then
    TEAM_ID="${APPLE_TEAM_ID:-}"
  fi
  if [[ -z "$TEAM_ID" ]]; then
    log_error "No team_id for project $project_id and APPLE_TEAM_ID not set in local.env"
    exit "$EC_ENVIRONMENT"
  fi

  if [[ -n "${OTA_CONFIGURATION_OVERRIDE:-}" ]]; then
    CONFIGURATION="$OTA_CONFIGURATION_OVERRIDE"
  fi

  AUTO_INCREMENT_BUILD="$(jq -r --arg id "$project_id" '.projects[$id].auto_increment_build // false' "$config_file")"
  if [[ "$AUTO_INCREMENT_BUILD" != "true" ]]; then
    AUTO_INCREMENT_BUILD="false"
  fi

  export PROJECT_ID DISPLAY_NAME PROJECT_PATH XCODEPROJ SCHEME CONFIGURATION BUNDLE_ID TEAM_ID AUTO_INCREMENT_BUILD
}

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g' | cut -c1-40
}

ota_url() {
  local url="$1"
  if [[ -n "${OTA_ACCESS_TOKEN:-}" ]]; then
    if [[ "$url" == *'?'* ]]; then
      printf '%s&token=%s' "$url" "$OTA_ACCESS_TOKEN"
    else
      printf '%s?token=%s' "$url" "$OTA_ACCESS_TOKEN"
    fi
  else
    printf '%s' "$url"
  fi
}

git_metadata() {
  local repo_path="$1"
  if git -C "$repo_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    GIT_BRANCH="$(git -C "$repo_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    GIT_COMMIT="$(git -C "$repo_path" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  else
    GIT_BRANCH="unknown"
    GIT_COMMIT="unknown"
  fi
  export GIT_BRANCH GIT_COMMIT
}

make_build_dir() {
  local timestamp branch_slug config_suffix dir_name
  timestamp="$(date '+%Y-%m-%d_%H%M')"
  branch_slug="$(slugify "$GIT_BRANCH")"
  config_suffix=""
  if [[ "${CONFIGURATION:-Release}" == "Debug" ]]; then
    config_suffix="-debug"
  fi
  dir_name="${timestamp}_${branch_slug}${config_suffix}"
  BUILD_OUTPUT_DIR="$OTA_BUILDS_DIR/$PROJECT_ID/$dir_name"
  mkdir -p "$BUILD_OUTPUT_DIR"
  export BUILD_OUTPUT_DIR BUILD_DIR_NAME="$dir_name"
}

check_disk_space() {
  local min_mb="${1:-5000}"
  local avail_kb
  avail_kb="$(df -k "$OTA_BUILDS_DIR" | awk 'NR==2 {print $4}')"
  if [[ "$avail_kb" -lt $((min_mb * 1024)) ]]; then
    log_error "Insufficient disk space (need ~${min_mb}MB free in $OTA_BUILDS_DIR)"
    exit "$EC_ENVIRONMENT"
  fi
}

write_summary_json() {
  local status="$1"
  local stage="${2:-}"
  local duration="${3:-0}"
  local install_url="${4:-}"
  local manifest_url="${5:-}"
  local ipa_url="${6:-}"
  local version="${7:-}"
  local build_number="${8:-}"
  local dashboard_url="${9:-}"

  local summary_file="$BUILD_OUTPUT_DIR/summary.json"
  local now
  now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  jq -n \
    --arg status "$status" \
    --arg project "$PROJECT_ID" \
    --arg display_name "$DISPLAY_NAME" \
    --arg branch "$GIT_BRANCH" \
    --arg commit "$GIT_COMMIT" \
    --arg date "$now" \
    --argjson duration "$duration" \
    --arg install_url "$install_url" \
    --arg manifest_url "$manifest_url" \
    --arg ipa_url "$ipa_url" \
    --arg dashboard_url "$dashboard_url" \
    --arg version "$version" \
    --arg build_number "$build_number" \
    --arg stage "$stage" \
    --arg build_dir "$BUILD_DIR_NAME" \
    '{
      status: $status,
      project: $project,
      display_name: $display_name,
      branch: $branch,
      commit: $commit,
      date: $date,
      duration_seconds: $duration,
      install_url: $install_url,
      manifest_url: $manifest_url,
      ipa_url: $ipa_url,
      dashboard_url: (if $dashboard_url == "" then null else $dashboard_url end),
      version: $version,
      build_number: $build_number,
      stage: (if $stage == "" then null else $stage end),
      build_dir: $build_dir
    }' >"$summary_file"

  export SUMMARY_FILE="$summary_file"
}

print_result_json() {
  if [[ -f "${SUMMARY_FILE:-}" ]]; then
    cat "$SUMMARY_FILE"
  fi
}

run_diagnostics() {
  local stage="$1"
  local build_dir="${BUILD_OUTPUT_DIR:-}"
  if [[ -z "$build_dir" || ! -d "$build_dir" ]]; then
    return 0
  fi
  python3 "$OTA_BUILDER_ROOT/tools/diagnose_xcodebuild_log.py" \
    --build-dir "$build_dir" \
    --stage "$stage" \
    --project "$PROJECT_ID" \
    --bundle-id "$BUNDLE_ID" \
    --team-id "$TEAM_ID" || true
}

read_archive_version() {
  local archive_path="$1"
  local info_plist
  info_plist="$(find "$archive_path/Products/Applications" -path '*.app/Info.plist' ! -path '*.appex/*' ! -path '*.framework/*' 2>/dev/null | head -1)"
  if [[ -z "$info_plist" || ! -f "$info_plist" ]]; then
    info_plist="$(find "$archive_path/Products/Applications" -name Info.plist -maxdepth 3 2>/dev/null | head -1)"
  fi
  if [[ -z "$info_plist" || ! -f "$info_plist" ]]; then
    APP_VERSION="unknown"
    APP_BUILD="unknown"
    return
  fi
  APP_VERSION="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$info_plist" 2>/dev/null || echo unknown)"
  APP_BUILD="$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$info_plist" 2>/dev/null || echo unknown)"
  export APP_VERSION APP_BUILD
}
