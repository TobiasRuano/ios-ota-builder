#!/usr/bin/env bash
# Resolve or rollback per-project build numbers for auto-increment OTA builds.
# Usage: resolve_build_number.sh resolve|rollback
#   resolve  — reserves and prints the build number to use (stdout); logs to stderr
#   rollback — restores counter after a failed build when safe (requires OTA_BUILD_NUMBER)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

BUILD_COUNTERS_FILE="$OTA_BUILDER_ROOT/config/build_counters.json"
BUILD_COUNTER_LOCK_DIR="$OTA_BUILDER_ROOT/config/build_counters.lock.d"

assert_integer_build() {
  local value="${1:-}"
  local source="$2"

  if [[ -z "$value" ]]; then
    return 0
  fi
  if [[ ! "$value" =~ ^(0|[1-9][0-9]*)$ ]]; then
    log_error "auto_increment_build requires integer CFBundleVersion values without leading zeros. Found \"$value\" in $source."
    log "Use an integer build number (e.g. 42, not 010 or 201.4) or disable auto_increment_build."
    exit "$EC_ENVIRONMENT"
  fi
}

acquire_build_counter_lock() {
  local start now
  start=$(date +%s)
  while ! mkdir "$BUILD_COUNTER_LOCK_DIR" 2>/dev/null; do
    sleep 0.1
    now=$(date +%s)
    if (( now - start >= 30 )); then
      log_error "Timed out waiting for build counter lock"
      exit "$EC_ENVIRONMENT"
    fi
  done
}

release_build_counter_lock() {
  rmdir "$BUILD_COUNTER_LOCK_DIR" 2>/dev/null || true
}

run_with_build_counter_lock() {
  acquire_build_counter_lock
  trap release_build_counter_lock EXIT
  "$@"
  trap - EXIT
  release_build_counter_lock
}

read_next_build() {
  local project_id="$1"
  local value=""

  if [[ ! -f "$BUILD_COUNTERS_FILE" ]]; then
    echo ""
    return 0
  fi
  value="$(jq -r --arg id "$project_id" '.[$id].next_build // empty' "$BUILD_COUNTERS_FILE" 2>/dev/null || echo "")"
  if [[ -n "$value" ]]; then
    assert_integer_build "$value" "counter"
  fi
  echo "$value"
}

write_next_build() {
  local project_id="$1"
  local next_build="$2"
  local tmp="${BUILD_COUNTERS_FILE}.tmp.$$"

  mkdir -p "$(dirname "$BUILD_COUNTERS_FILE")"
  if [[ -f "$BUILD_COUNTERS_FILE" ]]; then
    jq --arg id "$project_id" --argjson nb "$next_build" \
      '.[$id] = {next_build: $nb}' "$BUILD_COUNTERS_FILE" >"$tmp"
  else
    jq -n --arg id "$project_id" --argjson nb "$next_build" \
      '{($id): {next_build: $nb}}' >"$tmp"
  fi
  mv "$tmp" "$BUILD_COUNTERS_FILE"
}

get_project_build_number() {
  local project_file="$PROJECT_PATH/$XCODEPROJ"
  local raw_value probe_ok=0 published_max
  local -a derived_data_args=()

  if [[ -n "${DERIVED_DATA:-}" ]]; then
    derived_data_args=(-derivedDataPath "$DERIVED_DATA")
  fi

  set +e
  if [[ -n "${DERIVED_DATA:-}" ]]; then
    raw_value="$("$XCODEBUILD" -showBuildSettings \
      -project "$project_file" \
      -scheme "$SCHEME" \
      -configuration "$CONFIGURATION" \
      -derivedDataPath "$DERIVED_DATA" \
      2>/dev/null \
      | awk -F' = ' '/^[[:space:]]*CURRENT_PROJECT_VERSION = / { print $2; exit }')"
  else
    raw_value="$("$XCODEBUILD" -showBuildSettings \
      -project "$project_file" \
      -scheme "$SCHEME" \
      -configuration "$CONFIGURATION" \
      2>/dev/null \
      | awk -F' = ' '/^[[:space:]]*CURRENT_PROJECT_VERSION = / { print $2; exit }')"
  fi
  probe_ok=$?
  set -e

  if [[ $probe_ok -ne 0 ]] || [[ -z "${raw_value:-}" ]]; then
    published_max="$(get_max_published_build "$PROJECT_ID")"
    if (( published_max == 0 )); then
      log_error "Cannot seed build counter: project version unreadable and no prior successful OTA builds."
      log "Ensure Swift packages resolve and CURRENT_PROJECT_VERSION is readable, or publish a first build manually."
      exit "$EC_ENVIRONMENT"
    fi
    log "Warning: Could not read CURRENT_PROJECT_VERSION; using published builds only"
    echo "0"
    return 0
  fi

  assert_integer_build "$raw_value" "project"
  echo "$raw_value"
}

get_max_published_build() {
  local project_id="$1"
  local builds_dir="$OTA_BUILDS_DIR/$project_id"
  local bn max_build=0

  if [[ ! -d "$builds_dir" ]]; then
    echo "0"
    return 0
  fi

  while IFS= read -r bn; do
    [[ -z "$bn" || "$bn" == "null" ]] && continue
    assert_integer_build "$bn" "summary"
    if (( 10#${bn} > 10#${max_build} )); then
      max_build="$bn"
    fi
  done < <(find "$builds_dir" -name summary.json -print0 2>/dev/null \
    | xargs -0 jq -r 'select(.status == "success") | .build_number' 2>/dev/null || true)

  echo "$max_build"
}

compute_floor_build() {
  local project_build published_max base

  project_build="$(get_project_build_number)"
  published_max="$(get_max_published_build "$PROJECT_ID")"

  if (( 10#${project_build} > 10#${published_max} )); then
    base="$project_build"
  else
    base="$published_max"
  fi

  echo $((10#${base} + 1))
}

resolve_build_number_locked() {
  local stored floor assigned reserved

  floor="$(compute_floor_build)"
  stored="$(read_next_build "$PROJECT_ID")"

  if [[ -z "$stored" ]]; then
    assigned="$floor"
    log "Auto-increment build: seeded assignment $assigned for $PROJECT_ID"
  elif (( 10#${stored} < 10#${floor} )); then
    assigned="$floor"
    log "Auto-increment build: bumped assignment from $stored to $assigned"
  else
    assigned="$stored"
    log "Auto-increment build: reserved CFBundleVersion override $assigned"
  fi

  reserved=$((10#${assigned} + 1))
  write_next_build "$PROJECT_ID" "$reserved"
  log "Auto-increment build: next reservation will be $reserved"

  printf '%s\n' "$assigned"
}

rollback_build_number_locked() {
  local reserved="${OTA_BUILD_NUMBER:?OTA_BUILD_NUMBER required for rollback}"
  local counter

  counter="$(read_next_build "$PROJECT_ID")"
  if [[ -z "$counter" ]]; then
    return 0
  fi
  if (( 10#${counter} == 10#${reserved} + 1 )); then
    write_next_build "$PROJECT_ID" "$reserved"
    log "Auto-increment build: rolled back reservation to $reserved"
  fi
}

cmd_resolve() {
  run_with_build_counter_lock resolve_build_number_locked
}

cmd_rollback() {
  run_with_build_counter_lock rollback_build_number_locked
}

main() {
  load_config
  load_project "${PROJECT_ID:?PROJECT_ID required}"

  if [[ -n "${OTA_WORKSPACE_PATH:-}" ]]; then
    if [[ ! -d "$OTA_WORKSPACE_PATH" ]]; then
      log_error "Workspace path not found: $OTA_WORKSPACE_PATH"
      exit "$EC_ENVIRONMENT"
    fi
    PROJECT_PATH="$(cd "$OTA_WORKSPACE_PATH" && pwd)"
    export PROJECT_PATH
  fi

  case "${1:-}" in
    resolve)
      cmd_resolve
      ;;
    rollback)
      cmd_rollback
      ;;
    *)
      log_error "Usage: resolve_build_number.sh resolve|rollback"
      exit "$EC_ENVIRONMENT"
      ;;
  esac
}

main "$@"
