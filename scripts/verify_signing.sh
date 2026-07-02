#!/usr/bin/env bash
# Preflight signing verification for a project.
# Exit 10 (EC_ENVIRONMENT) if the environment is not ready.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

load_config

PROJECT_ID="${1:-}"
if [[ -z "$PROJECT_ID" ]]; then
  log_error "Usage: verify_signing.sh <project-id>"
  exit "$EC_ENVIRONMENT"
fi

load_project "$PROJECT_ID"

if [[ -n "${OTA_WORKSPACE_PATH:-}" ]]; then
  if [[ ! -d "$OTA_WORKSPACE_PATH" ]]; then
    log_error "Workspace path not found: $OTA_WORKSPACE_PATH"
    exit "$EC_ENVIRONMENT"
  fi
  PROJECT_PATH="$(cd "$OTA_WORKSPACE_PATH" && pwd)"
  export PROJECT_PATH
fi

log "Verifying signing environment for $DISPLAY_NAME ($PROJECT_ID)"

# Xcode / xcodebuild
if [[ ! -x "$XCODEBUILD" ]]; then
  log_error "xcodebuild not found at: $XCODEBUILD"
  log "Set XCODE_PATH in config/env.sh or export it before running."
  exit "$EC_ENVIRONMENT"
fi
log "xcodebuild: $XCODEBUILD ($("$XCODEBUILD" -version | head -1))"

# Project exists
PROJECT_FILE="$PROJECT_PATH/$XCODEPROJ"
if [[ ! -d "$PROJECT_FILE" ]]; then
  log_error "Xcode project not found: $PROJECT_FILE"
  exit "$EC_ENVIRONMENT"
fi
log "Project: $PROJECT_FILE"

# Signing identities
IDENTITIES="$(security find-identity -v -p codesigning 2>/dev/null || true)"
VALID_COUNT="$(echo "$IDENTITIES" | grep -c 'valid identities found' || true)"
if [[ "$VALID_COUNT" -eq 0 ]] || ! echo "$IDENTITIES" | grep -q "valid identities found"; then
  log_error "No valid code signing identities in keychain."
  log "Open Xcode → Settings → Accounts → select team → Manage Certificates."
  exit "$EC_ENVIRONMENT"
fi

HAS_DEV=false
HAS_DIST=false
if echo "$IDENTITIES" | grep -qi "Apple Development"; then HAS_DEV=true; fi
if echo "$IDENTITIES" | grep -qiE "Apple Distribution|iPhone Distribution"; then HAS_DIST=true; fi

if $HAS_DIST; then
  log "Signing identity: Apple Distribution found (preferred for Ad Hoc export)"
elif $HAS_DEV; then
  log "Signing identity: Apple Development found"
  log "Export method fallback: debugging (no local Distribution identity found)"
else
  log_error "No Apple Development or Distribution identity found."
  log "Open Xcode → Settings → Accounts → Manage Certificates → + Apple Distribution"
  exit "$EC_ENVIRONMENT"
fi

# Team check via xcodebuild showBuildSettings (lightweight)
log "Team ID configured: $TEAM_ID"
BUILD_SETTINGS="$("$XCODEBUILD" -showBuildSettings \
  -project "$PROJECT_FILE" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" 2>/dev/null | grep -E 'DEVELOPMENT_TEAM|PRODUCT_BUNDLE_IDENTIFIER' | head -5 || true)"

if [[ -n "$BUILD_SETTINGS" ]]; then
  echo "$BUILD_SETTINGS" | while read -r line; do log "  $line"; done
else
  log "Warning: could not read build settings (scheme may need package resolution first)"
fi

# Apple account session hint
if ! "$XCODEBUILD" -checkFirstLaunchStatus 2>/dev/null; then
  log "Note: Xcode first-launch components may need installation."
fi

log ""
log "Signing preflight passed for $PROJECT_ID."
log "Export uses automatic signing with -allowProvisioningUpdates."
if $HAS_DIST; then
  log "Preferred export method: ad-hoc"
else
  log "Fallback export method: debugging"
fi
log ""
log "If Ad Hoc export fails:"
log "  1. Register iPhone UDID at developer.apple.com → Devices"
log "  2. Xcode → Settings → Accounts → Download Manual Profiles"
log "  3. Xcode → Manage Certificates → + Apple Distribution"
log "  4. Re-run: agent_build_ota.sh $PROJECT_ID"

exit "$EC_SUCCESS"
