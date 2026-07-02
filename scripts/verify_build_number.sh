#!/usr/bin/env bash
# Preflight: ensure Info.plist uses $(CURRENT_PROJECT_VERSION) when auto_increment_build is on.
# Exit EC_ENVIRONMENT if the app target cannot honor xcodebuild build-number overrides.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

EXPECTED_CFBUNDLE_VERSION='$(CURRENT_PROJECT_VERSION)'

PROJECT_ID="${1:-}"
if [[ -z "$PROJECT_ID" ]]; then
  log_error "Usage: verify_build_number.sh <project-id>"
  exit "$EC_ENVIRONMENT"
fi

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

if [[ "${AUTO_INCREMENT_BUILD:-false}" != "true" ]]; then
  exit "$EC_SUCCESS"
fi

PROJECT_FILE="$PROJECT_PATH/$XCODEPROJ"
if [[ ! -d "$PROJECT_FILE" ]]; then
  log_error "Xcode project not found: $PROJECT_FILE"
  exit "$EC_ENVIRONMENT"
fi

log "Verifying build number configuration for $DISPLAY_NAME ($PROJECT_ID)"

settings="$("$XCODEBUILD" -showBuildSettings \
  -project "$PROJECT_FILE" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" 2>/dev/null || true)"

if [[ -z "$settings" ]]; then
  log_error "Could not read build settings for scheme $SCHEME"
  exit "$EC_ENVIRONMENT"
fi

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

app_target="$(printf '%s\n' "$settings" | sed -nE 's/^Build settings for action .* and target (.+):$/\1/p' | head -1)"
app_generate="$(printf '%s\n' "$settings" | sed -nE 's/^[[:space:]]*GENERATE_INFOPLIST_FILE[[:space:]]*=[[:space:]]*(.+)$/\1/p' | head -1)"
app_infoplist="$(printf '%s\n' "$settings" | sed -nE 's/^[[:space:]]*INFOPLIST_FILE[[:space:]]*=[[:space:]]*(.+)$/\1/p' | head -1)"
product_type="$(printf '%s\n' "$settings" | sed -nE 's/^[[:space:]]*PRODUCT_TYPE[[:space:]]*=[[:space:]]*(.+)$/\1/p' | head -1)"

app_target="$(trim "${app_target:-}")"
app_generate="$(trim "${app_generate:-NO}")"
app_infoplist="$(trim "${app_infoplist:-}")"
product_type="$(trim "${product_type:-}")"

if [[ "$product_type" != "com.apple.product-type.application" || -z "$app_target" ]]; then
  log_error "Could not find an application target in scheme $SCHEME"
  exit "$EC_ENVIRONMENT"
fi

log "  Application target: $app_target"

if [[ "$app_generate" == "YES" ]]; then
  log "  GENERATE_INFOPLIST_FILE = YES (build settings drive CFBundleVersion)"
  log "Build number preflight passed for $PROJECT_ID."
  exit "$EC_SUCCESS"
fi

if [[ -z "$app_infoplist" ]]; then
  log_error "Target $app_target has GENERATE_INFOPLIST_FILE = NO but no INFOPLIST_FILE"
  exit "$EC_ENVIRONMENT"
fi

plist_path="$PROJECT_PATH/$app_infoplist"
if [[ ! -f "$plist_path" ]]; then
  log_error "Info.plist not found: $plist_path"
  exit "$EC_ENVIRONMENT"
fi

cfbundle_version="$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$plist_path" 2>/dev/null || echo "")"
log "  INFOPLIST_FILE = $app_infoplist"
log "  CFBundleVersion = $cfbundle_version"

if [[ "$cfbundle_version" != "$EXPECTED_CFBUNDLE_VERSION" ]]; then
  log_error "CFBundleVersion in $plist_path must be $EXPECTED_CFBUNDLE_VERSION for auto_increment_build."
  log "Found: \"$cfbundle_version\""
  log "Edit Info.plist so OTA xcodebuild overrides apply without modifying the app repo each build."
  exit "$EC_ENVIRONMENT"
fi

log "Build number preflight passed for $PROJECT_ID."
exit "$EC_SUCCESS"
