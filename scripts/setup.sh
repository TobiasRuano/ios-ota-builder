#!/usr/bin/env bash
# First-time setup and migration to config/local.env + config/projects.json

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ENV="$ROOT/config/local.env"
LOCAL_EXAMPLE="$ROOT/config/local.env.example"
PROJECTS_JSON="$ROOT/config/projects.json"
PROJECTS_EXAMPLE="$ROOT/config/projects.json.example"

log() { printf '[setup] %s\n' "$*"; }

migrate_value_from_legacy() {
  local key="$1"
  local default="${2:-}"

  if [[ -f "$LOCAL_ENV" ]] && grep -q "^${key}=" "$LOCAL_ENV" 2>/dev/null; then
    return 0
  fi

  case "$key" in
    OTA_BASE_URL)
      if [[ -f "$ROOT/server/cloudflared/config.yml" ]]; then
        default="$(grep 'hostname:' "$ROOT/server/cloudflared/config.yml" | head -1 | awk '{print $2}')"
        if [[ -n "$default" ]]; then
          default="https://${default}"
        fi
      fi
      if [[ -z "$default" && -f "$HOME/.cloudflared/config.yml" ]]; then
        default="$(grep 'hostname:' "$HOME/.cloudflared/config.yml" | head -1 | awk '{print $2}')"
        if [[ -n "$default" ]]; then
          default="https://${default}"
        fi
      fi
      if [[ -z "$default" && -f "$ROOT/config/env.sh" ]] && grep -qE 'OTA_BASE_URL=.*yourdomain' "$ROOT/config/env.sh" 2>/dev/null; then
        :
      fi
      ;;
    OTA_ACCESS_TOKEN)
      if [[ -f "$ROOT/config/access.token" ]]; then
        default="$(tr -d '[:space:]' <"$ROOT/config/access.token")"
      fi
      ;;
    APPLE_TEAM_ID)
      if [[ -f "$PROJECTS_JSON" ]]; then
        default="$(jq -r '.projects | to_entries[0].value.team_id // empty' "$PROJECTS_JSON" 2>/dev/null || true)"
      fi
      if [[ -z "$default" && -f "$ROOT/config/ExportOptions.adhoc.plist" ]]; then
        default="$(plutil -extract teamID raw "$ROOT/config/ExportOptions.adhoc.plist" 2>/dev/null || true)"
      fi
      ;;
    OTA_HOSTNAME)
      if [[ -f "$ROOT/server/cloudflared/config.yml" ]]; then
        default="$(grep 'hostname:' "$ROOT/server/cloudflared/config.yml" | head -1 | awk '{print $2}')"
      fi
      ;;
    CLOUDFLARE_TUNNEL_ID)
      if [[ -f "$ROOT/server/cloudflared/config.yml" ]]; then
        default="$(grep '^tunnel:' "$ROOT/server/cloudflared/config.yml" | awk '{print $2}')"
      fi
      if [[ -z "$default" && -f "$HOME/.cloudflared/config.yml" ]]; then
        default="$(grep '^tunnel:' "$HOME/.cloudflared/config.yml" | awk '{print $2}')"
      fi
      ;;
    CLOUDFLARE_TUNNEL_NAME)
      default="ios-ota"
      ;;
  esac

  if [[ -n "$default" ]]; then
  log "Migrating $key from existing setup"
  fi
  echo "$default"
}

write_local_env() {
  local url token team hostname tunnel_id tunnel_name port

  url="$(migrate_value_from_legacy OTA_BASE_URL "")"
  token="$(migrate_value_from_legacy OTA_ACCESS_TOKEN "")"
  team="$(migrate_value_from_legacy APPLE_TEAM_ID "")"
  hostname="$(migrate_value_from_legacy OTA_HOSTNAME "")"
  tunnel_id="$(migrate_value_from_legacy CLOUDFLARE_TUNNEL_ID "")"
  tunnel_name="$(migrate_value_from_legacy CLOUDFLARE_TUNNEL_NAME "ios-ota")"
  port="${OTA_PORT:-8765}"

  if [[ -z "$token" ]]; then
    token="$(openssl rand -hex 32)"
    log "Generated new OTA_ACCESS_TOKEN"
  fi

  if [[ -z "$url" ]]; then
    read -r -p "OTA_BASE_URL (https://ota.yourdomain.com): " url
  fi
  if [[ -z "$team" ]]; then
    read -r -p "APPLE_TEAM_ID: " team
  fi
  if [[ -z "$hostname" ]]; then
    read -r -p "OTA_HOSTNAME (ota.yourdomain.com): " hostname
  fi
  if [[ -z "$tunnel_id" ]]; then
    read -r -p "CLOUDFLARE_TUNNEL_ID (optional, Enter to skip): " tunnel_id
  fi

  cat >"$LOCAL_ENV" <<EOF
# Private config — do not commit (gitignored)
OTA_BASE_URL=${url}
OTA_ACCESS_TOKEN=${token}
APPLE_TEAM_ID=${team}
OTA_HOSTNAME=${hostname}
CLOUDFLARE_TUNNEL_NAME=${tunnel_name}
CLOUDFLARE_TUNNEL_ID=${tunnel_id}
OTA_PORT=${port}
OTA_KEEP_BUILDS=10
OTA_MAX_AGE_DAYS=14
LAUNCHD_LABEL_PREFIX=com.local.ios-ota-builder
EOF
  chmod 600 "$LOCAL_ENV"
  log "Wrote $LOCAL_ENV (mode 600)"
}

main() {
  if [[ ! -f "$LOCAL_ENV" ]]; then
  if [[ -f "$LOCAL_EXAMPLE" ]]; then
    log "Creating config/local.env"
    write_local_env
  else
    echo "Missing $LOCAL_EXAMPLE" >&2
    exit 1
  fi
  else
    log "config/local.env already exists — skipping"
  fi

  if [[ ! -f "$PROJECTS_JSON" ]]; then
    if [[ -f "$PROJECTS_EXAMPLE" ]]; then
      cp "$PROJECTS_EXAMPLE" "$PROJECTS_JSON"
      log "Created config/projects.json from example — edit your app paths"
    fi
  else
    log "config/projects.json exists — keeping your projects"
  fi

  log "Done. Next steps:"
  echo "  1. Edit config/projects.json with your iOS apps"
  echo "  2. ./server/setup_cloudflared.sh"
  echo "  3. ./scripts/install_launchagents.sh"
  echo "  4. ./server/restart_server.sh"
  echo "  5. ./scripts/verify_signing.sh <project-id>"
}

main "$@"
