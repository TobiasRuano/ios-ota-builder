#!/usr/bin/env bash
# Render LaunchAgent plists from templates into ~/Library/LaunchAgents.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

if [[ ! -f "$ROOT/config/local.env" ]]; then
  echo "Missing config/local.env — run: $ROOT/scripts/setup.sh" >&2
  exit 1
fi

PREFIX="${LAUNCHD_LABEL_PREFIX:-com.local.ios-ota-builder}"
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST" "$ROOT/.server"

render_plist() {
  local template="$1"
  local out_name="$2"
  local out="$DEST/$out_name"
  sed \
    -e "s|OTA_BUILDER_ROOT_PLACEHOLDER|$ROOT|g" \
    -e "s|LAUNCHD_LABEL_PREFIX_PLACEHOLDER|$PREFIX|g" \
    -e "s|CLOUDFLARE_TUNNEL_NAME_PLACEHOLDER|${CLOUDFLARE_TUNNEL_NAME:-ios-ota}|g" \
    "$template" >"$out"
  echo "Wrote $out"
}

render_plist "$ROOT/launchd/com.local.ios-ota-builder.ota-server.plist.template" \
  "${PREFIX}.ota-server.plist"
render_plist "$ROOT/launchd/com.local.ios-ota-builder.ota-cloudflared.plist.template" \
  "${PREFIX}.ota-cloudflared.plist"
render_plist "$ROOT/launchd/com.local.ios-ota-builder.ota-nginx.plist.template" \
  "${PREFIX}.ota-nginx.plist"

echo ""
echo "Load services:"
echo "  launchctl bootstrap gui/\$(id -u) $DEST/${PREFIX}.ota-server.plist"
echo "  launchctl bootstrap gui/\$(id -u) $DEST/${PREFIX}.ota-cloudflared.plist"
