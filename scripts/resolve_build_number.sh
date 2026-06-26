#!/usr/bin/env bash
# Resolve or commit per-project build numbers for auto-increment OTA builds.
# Usage: resolve_build_number.sh resolve|commit
#   resolve — prints the build number to use (stdout); logs to stderr
#   commit  — increments next_build after a successful pipeline run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

BUILD_COUNTERS_FILE="$OTA_BUILDER_ROOT/config/build_counters.json"
BUILD_COUNTER_LOCK="$OTA_BUILDER_ROOT/config/build_counters.lock"

assert_integer_build() {
  local value="${1:-}"
  local source="$2"

  if [[ -z "$value" ]]; then
    return 0
  fi
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    log_error "auto_increment_build requires integer CFBundleVersion values. Found \"$value\" in $source."
    log "Use an integer build number or disable auto_increment_build."
    exit "$EC_ENVIRONMENT"
  fi
}

acquire_build_counter_lock() {
  exec 9>"$BUILD_COUNTER_LOCK"
  if ! flock -w 30 9; then
    log_error "Timed out waiting for build counter lock"
    exit "$EC_ENVIRONMENT"
  fi
}

release_build_counter_lock() {
  flock -u 9 2>/dev/null || true
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
  local raw_value probe_ok=0

  set +e
  raw_value="$("$XCODEBUILD" -showBuildSettings \
    -project "$project_file" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" 2>/dev/null \
    | awk -F' = ' '/^[[:space:]]*CURRENT_PROJECT_VERSION = / { print $2; exit }')"
  probe_ok=$?
  set -e

  if [[ $probe_ok -ne 0 ]] || [[ -z "${raw_value:-}" ]]; then
    log "Warning: Could not read CURRENT_PROJECT_VERSION (SPM may need resolution); using published builds only"
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
    if [[ "$bn" -gt "$max_build" ]]; then
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

  if [[ "$project_build" -gt "$published_max" ]]; then
    base="$project_build"
  else
    base="$published_max"
  fi

  echo $((base + 1))
}

resolve_build_number_locked() {
  local stored floor next_build

  floor="$(compute_floor_build)"
  stored="$(read_next_build "$PROJECT_ID")"

  if [[ -z "$stored" ]]; then
    next_build="$floor"
    write_next_build "$PROJECT_ID" "$next_build"
    log "Auto-increment build: seeded next_build=$next_build for $PROJECT_ID"
  elif [[ "$stored" -lt "$floor" ]]; then
    next_build="$floor"
    write_next_build "$PROJECT_ID" "$next_build"
    log "Auto-increment build: bumped stored counter from $stored to $next_build"
  else
    next_build="$stored"
    log "Auto-increment build: using CFBundleVersion override $next_build"
  fi

  printf '%s\n' "$next_build"
}

commit_build_number_locked() {
  local current next_build

  current="$(read_next_build "$PROJECT_ID")"
  if [[ -z "$current" ]]; then
    log_error "commit_build_number: no next_build stored for $PROJECT_ID"
    exit "$EC_ENVIRONMENT"
  fi
  next_build=$((current + 1))
  write_next_build "$PROJECT_ID" "$next_build"
  log "Auto-increment build: next build will be $next_build"
}

cmd_resolve() {
  acquire_build_counter_lock
  resolve_build_number_locked
  release_build_counter_lock
}

cmd_commit() {
  acquire_build_counter_lock
  commit_build_number_locked
  release_build_counter_lock
}

main() {
  load_config
  load_project "${PROJECT_ID:?PROJECT_ID required}"

  case "${1:-}" in
    resolve)
      cmd_resolve
      ;;
    commit)
      cmd_commit
      ;;
    *)
      log_error "Usage: resolve_build_number.sh resolve|commit"
      exit "$EC_ENVIRONMENT"
      ;;
  esac
}

main "$@"
