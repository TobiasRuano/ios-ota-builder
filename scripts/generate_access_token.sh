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

if grep -q '^OTA_ACCESS_TOKEN=' "$LOCAL_ENV"; then
  if [[ "$(uname)" == Darwin ]]; then
    sed -i '' "s/^OTA_ACCESS_TOKEN=.*/OTA_ACCESS_TOKEN=${TOKEN}/" "$LOCAL_ENV"
  else
    sed -i "s/^OTA_ACCESS_TOKEN=.*/OTA_ACCESS_TOKEN=${TOKEN}/" "$LOCAL_ENV"
  fi
else
  echo "OTA_ACCESS_TOKEN=${TOKEN}" >>"$LOCAL_ENV"
fi
chmod 600 "$LOCAL_ENV"

echo "OTA_ACCESS_TOKEN rotated in $LOCAL_ENV"
echo "Restart server: $ROOT/server/restart_server.sh"
