#!/usr/bin/env bash
# Central configuration loader for ios-ota-builder.
# Private values live in config/local.env (gitignored).
# Compatible with bash and zsh when sourced.

if [[ -n "${BASH_VERSION:-}" && -n "${BASH_SOURCE[0]:-}" ]]; then
  _CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "${ZSH_VERSION:-}" ]]; then
  # shellcheck disable=SC2296
  _CONFIG_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
  _CONFIG_DIR="${HOME}/Developer/ios-ota-builder/config"
fi

export OTA_BUILDER_ROOT="$(cd "$_CONFIG_DIR/.." && pwd)"
export OTA_BUILDS_DIR="$OTA_BUILDER_ROOT/OTA-Builds"
export OTA_PORT="${OTA_PORT:-8765}"
export OTA_KEEP_BUILDS="${OTA_KEEP_BUILDS:-10}"
export OTA_MAX_AGE_DAYS="${OTA_MAX_AGE_DAYS:-14}"
export LAUNCHD_LABEL_PREFIX="${LAUNCHD_LABEL_PREFIX:-com.local.ios-ota-builder}"

_LOCAL_ENV="$_CONFIG_DIR/local.env"
if [[ -f "$_LOCAL_ENV" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$_LOCAL_ENV"
  set +a
fi

# Legacy: migrate from config/access.token if present
if [[ -z "${OTA_ACCESS_TOKEN:-}" && -f "$_CONFIG_DIR/access.token" ]]; then
  OTA_ACCESS_TOKEN="$(tr -d '[:space:]' <"$_CONFIG_DIR/access.token")"
  export OTA_ACCESS_TOKEN
fi

# Xcode — defaults to active xcode-select; override in local.env if needed
if [[ -z "${XCODE_PATH:-}" ]]; then
  if [[ -d "/Applications/Xcode-beta.app" ]]; then
    export XCODE_PATH="/Applications/Xcode-beta.app/Contents/Developer"
  else
    export XCODE_PATH="$(xcode-select -p 2>/dev/null || echo "/Applications/Xcode.app/Contents/Developer")"
  fi
fi
export XCODEBUILD="${XCODEBUILD:-$XCODE_PATH/usr/bin/xcodebuild}"

unset _CONFIG_DIR _LOCAL_ENV
