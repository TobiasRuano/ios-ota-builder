#!/usr/bin/env bash
# Single entry point for iOS OTA builds.
# Usage: agent_build_ota.sh [--debug|--release] <project-id>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$SCRIPT_DIR"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

START_EPOCH=$(date +%s)
export START_EPOCH
FAILED_STAGE=""
FINAL_EC="$EC_SUCCESS"
BUILD_PUBLISHED=false
export BUILD_PUBLISHED

usage() {
  cat >&2 <<EOF
Usage: agent_build_ota.sh [options] <project-id>

Options:
  --debug              Archive/export using Debug configuration (overrides projects.json)
  --release            Archive/export using Release configuration (overrides projects.json)
  --dry-run            Run preflight only (signing, disk, server); no compile
  --workspace-path P   Build from this app repo path (e.g. a git worktree)
  --notes TEXT         Manual release notes (overrides auto-generated git log notes)
  -h, --help           Show this help

Examples:
  agent_build_ota.sh dev-quotes
  agent_build_ota.sh --dry-run dev-quotes
  agent_build_ota.sh --debug dev-quotes
  agent_build_ota.sh --release finanzio
  agent_build_ota.sh --notes "Fixed login crash" dev-quotes
EOF
}

parse_args() {
  PROJECT_ID=""
  OTA_CONFIGURATION_OVERRIDE=""
  OTA_WORKSPACE_PATH=""
  OTA_RELEASE_NOTES=""

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
      --dry-run)
        OTA_DRY_RUN=1
        shift
        ;;
      --workspace-path)
        if [[ $# -lt 2 ]]; then
          log_error "--workspace-path requires a path argument"
          usage
          exit "$EC_ENVIRONMENT"
        fi
        OTA_WORKSPACE_PATH="$2"
        shift 2
        ;;
      --notes)
        if [[ $# -lt 2 ]]; then
          log_error "--notes requires a value"
          usage
          exit "$EC_ENVIRONMENT"
        fi
        OTA_RELEASE_NOTES="$2"
        shift 2
        ;;
      -h | --help)
        OTA_NOTIFY_SKIP=1
        export OTA_NOTIFY_SKIP
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

  export OTA_CONFIGURATION_OVERRIDE OTA_DRY_RUN PROJECT_ID OTA_WORKSPACE_PATH OTA_RELEASE_NOTES
}

on_exit() {
  local ec=$?
  release_build_lock
  if [[ -z "${OTA_BUILD_NUMBER:-}" && -n "${BUILD_OUTPUT_DIR:-}" && -f "$BUILD_OUTPUT_DIR/.ota_build_number" ]]; then
    OTA_BUILD_NUMBER="$(<"$BUILD_OUTPUT_DIR/.ota_build_number")"
    export OTA_BUILD_NUMBER
  fi
  local effective_stage
  effective_stage="$(effective_build_stage)"
  if [[ -n "$effective_stage" ]]; then
    FAILED_STAGE="$effective_stage"
    export FAILED_STAGE
  fi
  if [[ "${BUILD_PUBLISHED:-false}" == "true" ]]; then
    print_result_json >&2 || true
    notify_build_result "$ec" || true
    return 0
  fi
  if [[ "${AUTO_INCREMENT_BUILD:-false}" == "true" && -n "${OTA_BUILD_NUMBER:-}" ]]; then
    "$OTA_BUILDER_ROOT/scripts/resolve_build_number.sh" rollback || true
  fi
  if [[ $ec -ne 0 && -n "${BUILD_OUTPUT_DIR:-}" && -d "$BUILD_OUTPUT_DIR" ]]; then
    run_diagnostics "${effective_stage:-unknown}"
    write_summary_json "failure" "${effective_stage:-unknown}" "$(($(date +%s) - START_EPOCH))" "" "" "" "${APP_VERSION:-}" "${APP_BUILD:-}" "" "" "$CONFIGURATION" "0" || true
    if [[ "${OTA_BUILD_STATUS:-0}" == "1" ]]; then
      write_build_status "failure" "${effective_stage:-unknown}" || true
    fi
    print_result_json >&2 || true
    purge_build_work "$BUILD_OUTPUT_DIR" || true
  fi
  notify_build_result "$ec" || true
  return "$ec"
}
trap on_exit EXIT

main() {
  parse_args "$@"

  if [[ -z "$PROJECT_ID" ]]; then
    log_error "Missing project-id"
    usage
    exit "$EC_ENVIRONMENT"
  fi

  if [[ "${OTA_DRY_RUN:-}" == "1" ]]; then
    export OTA_NOTIFY_SKIP=1
    load_config
    load_project "$PROJECT_ID"
    if [[ -n "${OTA_WORKSPACE_PATH:-}" ]]; then
      if [[ ! -d "$OTA_WORKSPACE_PATH" ]]; then
        log_error "Workspace path not found: $OTA_WORKSPACE_PATH"
        exit "$EC_ENVIRONMENT"
      fi
      PROJECT_PATH="$(cd "$OTA_WORKSPACE_PATH" && pwd)"
      export PROJECT_PATH
    fi
    run_dry_run_preflight
    exit $?
  fi

  OTA_BUILD_ATTEMPTED=true
  export OTA_BUILD_ATTEMPTED

  load_config
  load_project "$PROJECT_ID"
  if [[ -n "${OTA_WORKSPACE_PATH:-}" ]]; then
    if [[ ! -d "$OTA_WORKSPACE_PATH" ]]; then
      log_error "Workspace path not found: $OTA_WORKSPACE_PATH"
      exit "$EC_ENVIRONMENT"
    fi
    PROJECT_PATH="$(cd "$OTA_WORKSPACE_PATH" && pwd)"
    export PROJECT_PATH
  fi
  git_metadata "$PROJECT_PATH"
  if ! check_git_worktree "$PROJECT_PATH"; then
    FAILED_STAGE="environment"
    exit "$EC_ENVIRONMENT"
  fi
  check_disk_space 5000
  mkdir -p "$OTA_BUILDS_DIR"
  acquire_build_lock

  emit_build_stage environment

  log "=== OTA Build: $DISPLAY_NAME ($PROJECT_ID) ==="
  log "Configuration: $CONFIGURATION"
  log "Branch: $GIT_BRANCH | Commit: $GIT_COMMIT"

  # Preflight: signing
  if ! "$OTA_BUILDER_ROOT/scripts/verify_signing.sh" "$PROJECT_ID"; then
    FAILED_STAGE="environment"
    exit "$EC_ENVIRONMENT"
  fi

  if [[ "${AUTO_INCREMENT_BUILD:-false}" == "true" ]]; then
    if ! "$OTA_BUILDER_ROOT/scripts/verify_build_number.sh" "$PROJECT_ID"; then
      FAILED_STAGE="environment"
      exit "$EC_ENVIRONMENT"
    fi
    OTA_BUILD_NUMBER="$("$OTA_BUILDER_ROOT/scripts/resolve_build_number.sh" resolve)"
    export OTA_BUILD_NUMBER
  fi

  # Optional: warn if server down (non-blocking for local builds)
  if ! "$OTA_BUILDER_ROOT/scripts/serve_check.sh" 2>/dev/null; then
    log "Warning: OTA server not running. URLs will still be generated."
  fi

  make_build_dir
  export PROJECT_ID BUILD_OUTPUT_DIR

  emit_build_stage preparing

  # Archive
  if ! "$OTA_BUILDER_ROOT/scripts/build_archive.sh"; then
    exit "$EC_ARCHIVE"
  fi
  ARCHIVE_PATH="$BUILD_OUTPUT_DIR/work/app.xcarchive"

  if [[ -f "$BUILD_OUTPUT_DIR/.ota_build_number" ]]; then
    OTA_BUILD_NUMBER="$(<"$BUILD_OUTPUT_DIR/.ota_build_number")"
    export OTA_BUILD_NUMBER
  fi

  read_archive_version "$ARCHIVE_PATH"
  if [[ -n "${OTA_BUILD_NUMBER:-}" && "$APP_BUILD" != "$OTA_BUILD_NUMBER" ]]; then
    mismatch_msg="Archive CFBundleVersion ($APP_BUILD) does not match reserved build ($OTA_BUILD_NUMBER)."
    fix_msg="Ensure Info.plist sets CFBundleVersion to \$(CURRENT_PROJECT_VERSION)."
    printf '%s\n%s\n' "$mismatch_msg" "$fix_msg" >"$BUILD_OUTPUT_DIR/.ota_failure_reason"
    log_error "$mismatch_msg"
    log "$fix_msg"
    exit "$EC_ARCHIVE"
  fi

  make_ipa_filename
  make_build_label
  export IPA_FILENAME BUILD_LABEL

  # Export IPA
  if ! "$OTA_BUILDER_ROOT/scripts/export_ipa.sh" "$ARCHIVE_PATH" "$BUILD_OUTPUT_DIR"; then
    exit "$EC_EXPORT"
  fi

  read_archive_version "$ARCHIVE_PATH"

  emit_build_stage publishing

  # F04: extract app icon (non-blocking)
  ICON_REL_PATH=""
  if python3 "$OTA_BUILDER_ROOT/tools/extract_app_icon.py" \
    --archive "$ARCHIVE_PATH" \
    --output "$BUILD_OUTPUT_DIR/icon.png" >&2 \
    && [[ -f "$BUILD_OUTPUT_DIR/icon.png" ]]; then
    ICON_REL_PATH="/$PROJECT_ID/$BUILD_DIR_NAME/icon.png"
  fi

  # Drop DerivedData / xcarchive / export — IPA + icon already in build root
  purge_build_work "$BUILD_OUTPUT_DIR"

  # F05: release notes (before manifest — needed on install.html)
  if [[ -n "${OTA_RELEASE_NOTES:-}" ]]; then
    RELEASE_NOTES="$OTA_RELEASE_NOTES"
  else
    RELEASE_NOTES="$(collect_release_notes "$PROJECT_PATH" "$PROJECT_ID" "$BUILD_DIR_NAME")"
  fi
  export RELEASE_NOTES

  # Manifest + install page
  BUILD_DATE="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  export BUILD_DATE
  BASE_URL="${OTA_BASE_URL%/}"
  MANIFEST_ARGS=(
    --build-dir "$BUILD_OUTPUT_DIR"
    --base-url "$BASE_URL"
    --project-id "$PROJECT_ID"
    --build-dir-name "$BUILD_DIR_NAME"
    --display-name "$DISPLAY_NAME"
    --bundle-id "$BUNDLE_ID"
    --bundle-version "${APP_VERSION}.${APP_BUILD}"
    --ipa-filename "$IPA_FILENAME"
    --version "$APP_VERSION"
    --build-number "$APP_BUILD"
    --branch "$GIT_BRANCH"
    --commit "$GIT_COMMIT"
    --build-date "$BUILD_DATE"
    --configuration "$CONFIGURATION"
    --access-token "${OTA_ACCESS_TOKEN:-}"
  )
  if [[ -n "$ICON_REL_PATH" ]]; then
    MANIFEST_ARGS+=(--icon-filename icon.png)
  fi
  if [[ -n "$RELEASE_NOTES" ]]; then
    MANIFEST_ARGS+=(--release-notes "$RELEASE_NOTES")
  fi

  if ! python3 "$OTA_BUILDER_ROOT/tools/generate_manifest.py" \
    "${MANIFEST_ARGS[@]}" \
    >&2; then
    exit "$EC_MANIFEST"
  fi

  INSTALL_URL="$(ota_url "$BASE_URL/$PROJECT_ID/$BUILD_DIR_NAME/install.html")"
  MANIFEST_URL="$(ota_url "$BASE_URL/$PROJECT_ID/$BUILD_DIR_NAME/manifest.plist")"
  IPA_URL="$(ota_url "$BASE_URL/$PROJECT_ID/$BUILD_DIR_NAME/$IPA_FILENAME")"
  DASHBOARD_URL="$(ota_url "${BASE_URL}/")"
  LATEST_INSTALL_URL="$(ota_url "$BASE_URL/latest/$PROJECT_ID")"

  IPA_SIZE_BYTES="$(stat -f%z "$BUILD_OUTPUT_DIR/$IPA_FILENAME" 2>/dev/null || echo 0)"

  DURATION=$(($(date +%s) - START_EPOCH))
  write_summary_json "success" "" "$DURATION" "$INSTALL_URL" "$MANIFEST_URL" "$IPA_URL" "$APP_VERSION" "$APP_BUILD" "$DASHBOARD_URL" "$LATEST_INSTALL_URL" "$CONFIGURATION" "$IPA_SIZE_BYTES" "$IPA_FILENAME" "$BUILD_LABEL" "$ICON_REL_PATH" "$RELEASE_NOTES"
  if [[ "${OTA_BUILD_STATUS:-0}" == "1" ]]; then
    write_build_status "success" ""
  fi
  BUILD_PUBLISHED=true
  export BUILD_PUBLISHED

  emit_build_stage indexing

  if ! "$OTA_BUILDER_ROOT/scripts/cleanup_ota.sh" >&2; then
    exit "$EC_INDEX"
  fi

  log "=== Build succeeded in ${DURATION}s ==="
  log "Install: $INSTALL_URL"
  log "Latest: $LATEST_INSTALL_URL"
  log "Dashboard: $DASHBOARD_URL"
  print_result_json
}

main "$@"
