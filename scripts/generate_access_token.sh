#!/usr/bin/env bash
# Append or set OTA_ACCESS_TOKEN in config/local.env

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ENV="$ROOT/config/local.env"

if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "Run setup first: $ROOT/scripts/setup.sh" >&2
  exit 1
fi

TOKEN="$(openssl rand -hex 32)"
CREATED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

upsert_key() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$LOCAL_ENV"; then
    if [[ "$(uname)" == Darwin ]]; then
      sed -i '' "s|^${key}=.*|${key}=${value}|" "$LOCAL_ENV"
    else
      sed -i "s|^${key}=.*|${key}=${value}|" "$LOCAL_ENV"
    fi
  else
    echo "${key}=${value}" >>"$LOCAL_ENV"
  fi
}

upsert_key "OTA_ACCESS_TOKEN" "$TOKEN"
upsert_key "OTA_TOKEN_CREATED_AT" "$CREATED_AT"
chmod 600 "$LOCAL_ENV"

echo "OTA_ACCESS_TOKEN rotated in $LOCAL_ENV"
echo "OTA_TOKEN_CREATED_AT=${CREATED_AT}"
echo "Restart server: $ROOT/server/restart_server.sh"
