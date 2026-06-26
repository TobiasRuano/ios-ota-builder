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

log_warn() {
  log "WARN: $*"
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

sanitize_filename_part() {
  local value="$1"
  local max_len="${2:-30}"
  echo "$value" | sed -E 's/[^a-zA-Z0-9._-]+/_/g; s/_+$//; s/^_+//' | cut -c1-"$max_len"
}

make_ipa_filename() {
  local app_name branch env build_num version date_str
  app_name="$(sanitize_filename_part "${DISPLAY_NAME:-$PROJECT_ID}" 30)"
  version="${APP_VERSION:-unknown}"
  build_num="${APP_BUILD:-${OTA_BUILD_NUMBER:-unknown}}"
  env="${CONFIGURATION:-Release}"
  branch="$(slugify "${GIT_BRANCH:-unknown}")"
  branch="${branch:0:25}"
  date_str="$(date '+%Y-%m-%d')"
  IPA_FILENAME="${app_name}_${version}_${build_num}_${env}_${branch}_${date_str}.ipa"
  export IPA_FILENAME
}

make_build_label() {
  local build_num
  build_num="${APP_BUILD:-${OTA_BUILD_NUMBER:-unknown}}"
  BUILD_LABEL="#${build_num} · $(date '+%d %b')"
  export BUILD_LABEL
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

check_git_worktree() {
  local repo_path="$1"
  local porcelain count

  GIT_DIRTY_COUNT=0
  export GIT_DIRTY_COUNT

  if ! git -C "$repo_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  porcelain="$(git -C "$repo_path" status --porcelain 2>/dev/null || true)"
  if [[ -z "$porcelain" ]]; then
    return 0
  fi

  count="$(printf '%s\n' "$porcelain" | wc -l | tr -d ' ')"
  GIT_DIRTY_COUNT="$count"
  export GIT_DIRTY_COUNT

  log_warn "Project repo has $count uncommitted change(s) in $repo_path — the IPA may not match an exact commit and reproduction may be difficult."

  if [[ "${OTA_FAIL_ON_DIRTY:-0}" == "1" ]]; then
    log_error "OTA_FAIL_ON_DIRTY=1: refusing to build with a dirty git worktree."
    return 1
  fi

  return 0
}

make_build_dir() {
  local dir_name date_prefix
  if [[ -n "${OTA_BUILD_NUMBER:-}" ]]; then
    date_prefix="$(date '+%d-%m')"
    dir_name="${date_prefix}-${OTA_BUILD_NUMBER}"
  else
    dir_name="$(date '+%d-%m-%H%M%S')"
  fi
  BUILD_OUTPUT_DIR="$OTA_BUILDS_DIR/$PROJECT_ID/$dir_name"
  if [[ -d "$BUILD_OUTPUT_DIR" ]]; then
    rm -f "$BUILD_OUTPUT_DIR"/*.ipa \
          "$BUILD_OUTPUT_DIR/install.html" \
          "$BUILD_OUTPUT_DIR/manifest.plist" \
          "$BUILD_OUTPUT_DIR/summary.json" \
          "$BUILD_OUTPUT_DIR/icon.png" \
          "$BUILD_OUTPUT_DIR/diagnostics.md" \
          "$BUILD_OUTPUT_DIR/.ota_failure_reason"
    rm -rf "$BUILD_OUTPUT_DIR/work"
  fi
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
  local latest_install_url="${10:-}"
  local configuration="${11:-${CONFIGURATION:-}}"
  local ipa_size_bytes="${12:-0}"
  local ipa_filename="${13:-${IPA_FILENAME:-app.ipa}}"
  local build_label="${14:-${BUILD_LABEL:-}}"
  local icon_path="${15:-}"

  local summary_file="$BUILD_OUTPUT_DIR/summary.json"
  local now
  now="${BUILD_DATE:-$(date -u '+%Y-%m-%dT%H:%M:%SZ')}"

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
    --arg latest_install_url "$latest_install_url" \
    --arg version "$version" \
    --arg build_number "$build_number" \
    --arg stage "$stage" \
    --arg build_dir "$BUILD_DIR_NAME" \
    --arg configuration "$configuration" \
    --argjson ipa_size_bytes "$ipa_size_bytes" \
    --arg ipa_filename "$ipa_filename" \
    --arg build_label "$build_label" \
    --arg icon_path "$icon_path" \
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
      latest_install_url: (if $latest_install_url == "" then null else $latest_install_url end),
      version: $version,
      build_number: $build_number,
      stage: (if $stage == "" then null else $stage end),
      build_dir: $build_dir,
      configuration: (if $configuration == "" then null else $configuration end),
      ipa_size_bytes: (if $ipa_size_bytes == 0 then null else $ipa_size_bytes end),
      ipa_filename: (if $ipa_filename == "" then null else $ipa_filename end),
      build_label: (if $build_label == "" then null else $build_label end),
      icon_path: (if $icon_path == "" then null else $icon_path end)
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

format_duration_human() {
  local total="${1:-0}"
  local minutes seconds
  if [[ "$total" -ge 60 ]]; then
    minutes=$((total / 60))
    seconds=$((total % 60))
    if [[ "$seconds" -eq 0 ]]; then
      printf '%dm' "$minutes"
    else
      printf '%dm %ds' "$minutes" "$seconds"
    fi
  else
    printf '%ds' "$total"
  fi
}

_escape_osascript() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

notify_build_result() {
  local ec="${1:-0}"
  local webhook_url="${OTA_WEBHOOK_URL:-}"

  if [[ "${OTA_NOTIFY_SKIP:-}" == "1" || "${OTA_BUILD_ATTEMPTED:-}" != "true" ]]; then
    return 0
  fi
  if [[ "${OTA_NOTIFY:-1}" == "0" && -z "$webhook_url" ]]; then
    return 0
  fi

  local duration=0
  if [[ -n "${START_EPOCH:-}" ]]; then
    duration=$(($(date +%s) - START_EPOCH))
  fi

  local notify_status="failure"
  if [[ "$ec" -eq 0 && "${BUILD_PUBLISHED:-false}" == "true" ]]; then
    notify_status="success"
  fi

  local label="${DISPLAY_NAME:-}"
  if [[ -z "$label" ]]; then
    label="${PROJECT_ID:-OTA build}"
  fi

  local stage="${FAILED_STAGE:-}"
  local install_path=""
  if [[ "$notify_status" == "success" && -n "${PROJECT_ID:-}" && -n "${BUILD_DIR_NAME:-}" ]]; then
    install_path="/${PROJECT_ID}/${BUILD_DIR_NAME}/install.html"
  fi

  local duration_human
  duration_human="$(format_duration_human "$duration")"
  local message title
  if [[ "$notify_status" == "success" ]]; then
    message="${label} build succeeded (${duration_human})"
    title="OTA build succeeded"
  else
    if [[ -n "$stage" ]]; then
      message="${label} build failed at ${stage} (${duration_human})"
    else
      message="${label} build failed (${duration_human})"
    fi
    title="OTA build failed"
  fi

  if [[ "${OTA_NOTIFY:-1}" != "0" ]]; then
    local safe_message safe_title
    safe_message="$(_escape_osascript "$message")"
    safe_title="$(_escape_osascript "$title")"
    osascript -e "display notification \"${safe_message}\" with title \"${safe_title}\"" 2>/dev/null || true
  fi

  if [[ -n "$webhook_url" ]]; then
    local payload
    payload="$(jq -n \
      --arg status "$notify_status" \
      --arg project "${PROJECT_ID:-}" \
      --arg display_name "${DISPLAY_NAME:-}" \
      --argjson duration_seconds "$duration" \
      --arg stage "$stage" \
      --arg install_path "$install_path" \
      '{
        status: $status,
        project: (if $project == "" then null else $project end),
        display_name: (if $display_name == "" then null else $display_name end),
        duration_seconds: $duration_seconds
      }
      + (if $stage == "" then {} else {stage: $stage} end)
      + (if $install_path == "" then {} else {install_path: $install_path} end)')"

    local curl_args=(-sf --max-time 10 -X POST -H "Content-Type: application/json" -d "$payload")
    if [[ -n "${OTA_WEBHOOK_SECRET:-}" ]]; then
      curl_args+=(-H "X-OTA-Webhook-Secret: ${OTA_WEBHOOK_SECRET}")
    fi
    if ! curl "${curl_args[@]}" "$webhook_url" >/dev/null 2>&1; then
      log "Warning: build completion webhook failed"
    fi
  fi
}
