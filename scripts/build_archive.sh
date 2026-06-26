#!/usr/bin/env bash
# Resolve SPM dependencies and create archive.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

load_config
load_project "${PROJECT_ID:?PROJECT_ID required}"

PROJECT_FILE="$PROJECT_PATH/$XCODEPROJ"
WORK_DIR="$BUILD_OUTPUT_DIR/work"
DERIVED_DATA="$WORK_DIR/DerivedData"
ARCHIVE_PATH="$WORK_DIR/app.xcarchive"
RESOLVE_LOG="$BUILD_OUTPUT_DIR/build.log"
ARCHIVE_LOG="$BUILD_OUTPUT_DIR/archive.log"

mkdir -p "$WORK_DIR"
export DERIVED_DATA ARCHIVE_PATH WORK_DIR

log "Resolving package dependencies..."
set +e
"$XCODEBUILD" -resolvePackageDependencies \
  -project "$PROJECT_FILE" \
  -scheme "$SCHEME" \
  -derivedDataPath "$DERIVED_DATA" \
  >"$RESOLVE_LOG" 2>&1
RESOLVE_EC=$?
set -e

cat "$RESOLVE_LOG" >>"$ARCHIVE_LOG" 2>/dev/null || true
if [[ $RESOLVE_EC -ne 0 ]]; then
  log_error "Package dependency resolution failed (exit $RESOLVE_EC)"
  cp "$RESOLVE_LOG" "$BUILD_OUTPUT_DIR/build.log"
  exit "$EC_DEPENDENCIES"
fi
log "Dependencies resolved."

log "Archiving $SCHEME ($CONFIGURATION)..."
set +e
"$XCODEBUILD" archive \
  -project "$PROJECT_FILE" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -archivePath "$ARCHIVE_PATH" \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA" \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  >>"$ARCHIVE_LOG" 2>&1
ARCHIVE_EC=$?
set -e

if [[ $ARCHIVE_EC -ne 0 ]]; then
  log_error "Archive failed (exit $ARCHIVE_EC). See $ARCHIVE_LOG"
  exit "$EC_ARCHIVE"
fi

if [[ ! -d "$ARCHIVE_PATH" ]]; then
  log_error "Archive not found at $ARCHIVE_PATH"
  exit "$EC_ARCHIVE"
fi

read_archive_version "$ARCHIVE_PATH"
log "Archive succeeded. Version: $APP_VERSION ($APP_BUILD)"
