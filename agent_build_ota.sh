#!/usr/bin/env bash
# Single entry point for iOS OTA builds.
# Usage: agent_build_ota.sh [--debug|--release] <project-id>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$SCRIPT_DIR"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

START_EPOCH=$(date +%s)
FAILED_STAGE=""
FINAL_EC="$EC_SUCCESS"

usage() {
  cat >&2 <<EOF
Usage: agent_build_ota.sh [options] <project-id>

Options:
  --debug     Archive/export using Debug configuration (overrides projects.json)
  --release   Archive/export using Release configuration (overrides projects.json)
  -h, --help  Show this help

Examples:
  agent_build_ota.sh dev-quotes
  agent_build_ota.sh --debug dev-quotes
  agent_build_ota.sh --release finanzio
EOF
}

parse_args() {
  PROJECT_ID=""
  OTA_CONFIGURATION_OVERRIDE=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --debug)
        OTA_CONFIGURATION_OVERRIDE="Debug"
        shift
        ;;
      --release)
        OTA_CONFIGURATION_OVERRIDE="Release"
        shift
        ;;
      -h | --help)
        usage
        exit "$EC_SUCCESS"
        ;;
      --)
        shift
        break
        ;;
      -*)
        log_error "Unknown option: $1"
        usage
        exit "$EC_ENVIRONMENT"
        ;;
      *)
        if [[ -z "$PROJECT_ID" ]]; then
          PROJECT_ID="$1"
        else
          log_error "Unexpected argument: $1"
          usage
          exit "$EC_ENVIRONMENT"
        fi
        shift
        ;;
    esac
  done

  export OTA_CONFIGURATION_OVERRIDE PROJECT_ID
}

cleanup_on_fail() {
  local ec=$?
  if [[ $ec -ne 0 && -n "${BUILD_OUTPUT_DIR:-}" && -d "$BUILD_OUTPUT_DIR" ]]; then
    run_diagnostics "${FAILED_STAGE:-unknown}"
    write_summary_json "failure" "${FAILED_STAGE:-unknown}" "$(($(date +%s) - START_EPOCH))" "" "" "" "${APP_VERSION:-}" "${APP_BUILD:-}" || true
    print_result_json >&2 || true
  fi
}
trap cleanup_on_fail EXIT

main() {
  parse_args "$@"

  if [[ -z "$PROJECT_ID" ]]; then
    log_error "Missing project-id"
    usage
    exit "$EC_ENVIRONMENT"
  fi

  load_config
  load_project "$PROJECT_ID"
  git_metadata "$PROJECT_PATH"
  check_disk_space 5000
  mkdir -p "$OTA_BUILDS_DIR"

  log "=== OTA Build: $DISPLAY_NAME ($PROJECT_ID) ==="
  log "Configuration: $CONFIGURATION"
  log "Branch: $GIT_BRANCH | Commit: $GIT_COMMIT"

  # Preflight: signing
  if ! "$OTA_BUILDER_ROOT/scripts/verify_signing.sh" "$PROJECT_ID"; then
    FAILED_STAGE="environment"
    exit "$EC_ENVIRONMENT"
  fi

  # Optional: warn if server down (non-blocking for local builds)
  if ! "$OTA_BUILDER_ROOT/scripts/serve_check.sh" 2>/dev/null; then
    log "Warning: OTA server not running. URLs will still be generated."
  fi

  make_build_dir
  export PROJECT_ID BUILD_OUTPUT_DIR

  # Archive
  if ! "$OTA_BUILDER_ROOT/scripts/build_archive.sh"; then
    FAILED_STAGE="archive"
    exit "$EC_ARCHIVE"
  fi
  ARCHIVE_PATH="$BUILD_OUTPUT_DIR/work/app.xcarchive"

  # Export IPA
  if ! "$OTA_BUILDER_ROOT/scripts/export_ipa.sh" "$ARCHIVE_PATH" "$BUILD_OUTPUT_DIR"; then
    FAILED_STAGE="export"
    exit "$EC_EXPORT"
  fi

  read_archive_version "$ARCHIVE_PATH"

  # Manifest + install page
  BASE_URL="${OTA_BASE_URL%/}"
  if ! python3 "$OTA_BUILDER_ROOT/tools/generate_manifest.py" \
    --build-dir "$BUILD_OUTPUT_DIR" \
    --base-url "$BASE_URL" \
    --project-id "$PROJECT_ID" \
    --build-dir-name "$BUILD_DIR_NAME" \
    --display-name "$DISPLAY_NAME" \
    --bundle-id "$BUNDLE_ID" \
    --bundle-version "${APP_VERSION}.${APP_BUILD}" \
    --access-token "${OTA_ACCESS_TOKEN:-}" \
    >&2; then
    FAILED_STAGE="manifest"
    exit "$EC_MANIFEST"
  fi

  INSTALL_URL="$(ota_url "$BASE_URL/$PROJECT_ID/$BUILD_DIR_NAME/install.html")"
  MANIFEST_URL="$(ota_url "$BASE_URL/$PROJECT_ID/$BUILD_DIR_NAME/manifest.plist")"
  IPA_URL="$(ota_url "$BASE_URL/$PROJECT_ID/$BUILD_DIR_NAME/app.ipa")"
  DASHBOARD_URL="$(ota_url "${BASE_URL}/")"

  DURATION=$(($(date +%s) - START_EPOCH))
  write_summary_json "success" "" "$DURATION" "$INSTALL_URL" "$MANIFEST_URL" "$IPA_URL" "$APP_VERSION" "$APP_BUILD" "$DASHBOARD_URL"

  if ! "$OTA_BUILDER_ROOT/scripts/cleanup_ota.sh" >&2; then
    FAILED_STAGE="index"
    exit "$EC_INDEX"
  fi

  trap - EXIT
  log "=== Build succeeded in ${DURATION}s ==="
  log "Install: $INSTALL_URL"
  log "Dashboard: $DASHBOARD_URL"
  print_result_json
}

main "$@"
