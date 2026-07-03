#!/usr/bin/env bash
# Export archive to Ad Hoc IPA.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

load_config

TEAM_ID="${TEAM_ID:-${APPLE_TEAM_ID:-}}"
if [[ -z "$TEAM_ID" ]]; then
  log_error "TEAM_ID not set. Run export via agent_build_ota.sh or set APPLE_TEAM_ID in local.env"
  exit "$EC_EXPORT"
fi

ARCHIVE_PATH="${1:-}"
BUILD_OUTPUT_DIR="${2:-${BUILD_OUTPUT_DIR:-}}"

if [[ -z "$ARCHIVE_PATH" || -z "$BUILD_OUTPUT_DIR" ]]; then
  log_error "Usage: export_ipa.sh <archive-path> <build-output-dir>"
  exit "$EC_EXPORT"
fi

EXPORT_DIR="$BUILD_OUTPUT_DIR/work/export"
EXPORT_LOG="$BUILD_OUTPUT_DIR/export.log"
EXPORT_OPTIONS="$BUILD_OUTPUT_DIR/work/ExportOptions.adhoc.plist"
TEMPLATE="$OTA_BUILDER_ROOT/config/ExportOptions.adhoc.plist.template"

mkdir -p "$EXPORT_DIR" "$(dirname "$EXPORT_OPTIONS")"

EXPORT_METHOD="${OTA_EXPORT_METHOD:-}"
if [[ -z "$EXPORT_METHOD" ]]; then
  IDENTITIES="$(security find-identity -v -p codesigning 2>/dev/null || true)"
  if echo "$IDENTITIES" | grep -qiE "Apple Distribution|iPhone Distribution"; then
    EXPORT_METHOD="ad-hoc"
  else
    EXPORT_METHOD="debugging"
  fi
fi

sed \
  -e "s/TEAM_ID_PLACEHOLDER/$TEAM_ID/g" \
  -e "s/EXPORT_METHOD_PLACEHOLDER/$EXPORT_METHOD/g" \
  "$TEMPLATE" >"$EXPORT_OPTIONS"

log "Exporting IPA (method: $EXPORT_METHOD)..."
emit_build_stage exporting
set +e
"$XCODEBUILD" -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates \
  >"$EXPORT_LOG" 2>&1
EXPORT_EC=$?
set -e

if [[ $EXPORT_EC -ne 0 ]]; then
  log_error "Export failed (exit $EXPORT_EC). See $EXPORT_LOG"
  exit "$EC_EXPORT"
fi

IPA_SRC="$(find "$EXPORT_DIR" -name '*.ipa' -maxdepth 1 | head -1)"
if [[ -z "$IPA_SRC" ]]; then
  log_error "No IPA found in $EXPORT_DIR"
  exit "$EC_EXPORT"
fi

IPA_DEST="$BUILD_OUTPUT_DIR/${IPA_FILENAME:-app.ipa}"
cp "$IPA_SRC" "$IPA_DEST"
log "IPA exported: $IPA_DEST"
