#!/usr/bin/env bash
# Rotate OTA_ACCESS_TOKEN when OTA_TOKEN_ROTATE_DAYS has elapsed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

LOCAL_ENV="$ROOT/config/local.env"
if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "Missing config/local.env" >&2
  exit 1
fi

rotate_days="${OTA_TOKEN_ROTATE_DAYS:-0}"
if [[ "$rotate_days" -le 0 ]]; then
  exit 0
fi

created_at="${OTA_TOKEN_CREATED_AT:-}"
if [[ -z "$created_at" ]]; then
  echo "[token-rotation] OTA_TOKEN_CREATED_AT missing — setting timestamp without rotating"
  created_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  if grep -q '^OTA_TOKEN_CREATED_AT=' "$LOCAL_ENV"; then
    if [[ "$(uname)" == Darwin ]]; then
      sed -i '' "s|^OTA_TOKEN_CREATED_AT=.*|OTA_TOKEN_CREATED_AT=${created_at}|" "$LOCAL_ENV"
    else
      sed -i "s|^OTA_TOKEN_CREATED_AT=.*|OTA_TOKEN_CREATED_AT=${created_at}|" "$LOCAL_ENV"
    fi
  else
    echo "OTA_TOKEN_CREATED_AT=${created_at}" >>"$LOCAL_ENV"
  fi
  exit 0
fi

due="$(
  python3 - "$created_at" "$rotate_days" <<'PY'
import sys
from datetime import datetime, timedelta, timezone

created_raw, days_raw = sys.argv[1:3]
days = int(days_raw)
created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
if created.tzinfo is None:
    created = created.replace(tzinfo=timezone.utc)
expires = created + timedelta(days=days)
print("1" if datetime.now(timezone.utc) >= expires else "0")
PY
)"

if [[ "$due" != "1" ]]; then
  exit 0
fi

echo "[token-rotation] Token expired after ${rotate_days} days — rotating"
"$ROOT/scripts/generate_access_token.sh"
"$ROOT/server/restart_server.sh"
