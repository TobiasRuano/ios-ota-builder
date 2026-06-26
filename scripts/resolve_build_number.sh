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

numeric_build() {
  local value="${1:-}"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$value"
  else
    echo "0"
  fi
}

read_next_build() {
  local project_id="$1"
  if [[ ! -f "$BUILD_COUNTERS_FILE" ]]; then
    echo ""
    return 0
  fi
  jq -r --arg id "$project_id" '.[$id].next_build // empty' "$BUILD_COUNTERS_FILE" 2>/dev/null || echo ""
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
  local value

  value="$("$XCODEBUILD" -showBuildSettings \
    -project "$project_file" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" 2>/dev/null \
    | awk -F' = ' '/^[[:space:]]*CURRENT_PROJECT_VERSION = / { print $2; exit }')"

  numeric_build "$value"
}

get_max_published_build() {
  local project_id="$1"
  local builds_dir="$OTA_BUILDS_DIR/$project_id"
  local max_build

  if [[ ! -d "$builds_dir" ]]; then
    echo "0"
    return 0
  fi

  max_build="$(find "$builds_dir" -name summary.json -print0 2>/dev/null \
    | xargs -0 jq -r 'select(.status == "success") | .build_number' 2>/dev/null \
    | grep -E '^[0-9]+$' \
    | sort -n \
    | tail -1 || true)"

  numeric_build "$max_build"
}

seed_next_build() {
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

cmd_resolve() {
  local next_build

  next_build="$(read_next_build "$PROJECT_ID")"
  if [[ -z "$next_build" ]]; then
    next_build="$(seed_next_build)"
    write_next_build "$PROJECT_ID" "$next_build"
    log "Auto-increment build: seeded next_build=$next_build for $PROJECT_ID"
  else
    next_build="$(numeric_build "$next_build")"
    log "Auto-increment build: using CFBundleVersion override $next_build"
  fi

  printf '%s\n' "$next_build"
}

cmd_commit() {
  local current next_build

  current="$(read_next_build "$PROJECT_ID")"
  if [[ -z "$current" ]]; then
    log_error "commit_build_number: no next_build stored for $PROJECT_ID"
    exit "$EC_ENVIRONMENT"
  fi
  current="$(numeric_build "$current")"
  next_build=$((current + 1))
  write_next_build "$PROJECT_ID" "$next_build"
  log "Auto-increment build: next build will be $next_build"
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
