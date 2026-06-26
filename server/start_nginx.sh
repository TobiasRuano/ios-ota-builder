#!/usr/bin/env bash
# Start nginx serving OTA-Builds. Installs nginx via Homebrew if missing.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

mkdir -p "$ROOT/.server"
NGINX_BIN=""
if command -v nginx >/dev/null 2>&1; then
  NGINX_BIN="$(command -v nginx)"
elif [[ -x /opt/homebrew/bin/nginx ]]; then
  NGINX_BIN="/opt/homebrew/bin/nginx"
elif [[ -x /usr/local/bin/nginx ]]; then
  NGINX_BIN="/usr/local/bin/nginx"
else
  echo "Installing nginx via Homebrew..."
  brew install nginx
  NGINX_BIN="$(brew --prefix nginx)/bin/nginx"
fi

CONF_GENERATED="$ROOT/.server/nginx.generated.conf"
sed \
  -e "s|__OTA_BUILDER_ROOT__|$ROOT|g" \
  -e "s|__OTA_BUILDS_DIR__|$OTA_BUILDS_DIR|g" \
  -e "s|__OTA_PORT__|$OTA_PORT|g" \
  "$ROOT/server/nginx.conf" >"$CONF_GENERATED"

"$NGINX_BIN" -t -c "$CONF_GENERATED" -p "$ROOT/.server"
"$NGINX_BIN" -c "$CONF_GENERATED" -p "$ROOT/.server"
echo "nginx serving $OTA_BUILDS_DIR at http://127.0.0.1:$OTA_PORT/"
