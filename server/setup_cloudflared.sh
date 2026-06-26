#!/usr/bin/env bash
# Render ~/.cloudflared/config.yml from template + local.env

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=config/env.sh
source "$ROOT/config/env.sh"

if [[ -z "${CLOUDFLARE_TUNNEL_ID:-}" || -z "${OTA_HOSTNAME:-}" ]]; then
  echo "Set CLOUDFLARE_TUNNEL_ID and OTA_HOSTNAME in config/local.env first." >&2
  echo "Run: $ROOT/scripts/setup.sh" >&2
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Installing cloudflared..."
  brew install cloudflared
fi

mkdir -p "$HOME/.cloudflared"
OUT="$HOME/.cloudflared/config.yml"
TEMPLATE="$ROOT/server/cloudflared/config.yml.template"

sed \
  -e "s|CLOUDFLARE_TUNNEL_ID_PLACEHOLDER|$CLOUDFLARE_TUNNEL_ID|g" \
  -e "s|OTA_HOSTNAME_PLACEHOLDER|$OTA_HOSTNAME|g" \
  -e "s|OTA_PORT_PLACEHOLDER|${OTA_PORT:-8765}|g" \
  -e "s|HOME_PLACEHOLDER|$HOME|g" \
  "$TEMPLATE" >"$OUT"

echo "Wrote $OUT"
echo ""
echo "If tunnel not created yet:"
echo "  cloudflared tunnel login"
echo "  cloudflared tunnel create ${CLOUDFLARE_TUNNEL_NAME:-ios-ota}"
echo "  cloudflared tunnel route dns ${CLOUDFLARE_TUNNEL_NAME:-ios-ota} $OTA_HOSTNAME"
echo ""
echo "Then install LaunchAgents:"
echo "  $ROOT/scripts/install_launchagents.sh"
