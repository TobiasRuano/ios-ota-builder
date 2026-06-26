#!/usr/bin/env bash
# Ops status: projects, latest builds, disk, and local server reachability.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

JSON_MODE=0

usage() {
  cat >&2 <<EOF
Usage: ota_status.sh [options]

Options:
  --json      Machine-readable JSON on stdout (for agents)
  -h, --help  Show this help

Exit codes:
  0   All checks passed (or failures ignored via OTA_STATUS_FAIL_ON_*)
  10  Disk below OTA_STATUS_MIN_DISK_MB (default 5000)
  60  Local OTA server not reachable
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)
        JSON_MODE=1
        shift
        ;;
      -h | --help)
        usage
        exit "$EC_SUCCESS"
        ;;
      --)
        shift
        break
        ;;
      -*)
        log_error "Unknown option: $1"
        usage
        exit "$EC_ENVIRONMENT"
        ;;
      *)
        log_error "Unexpected argument: $1"
        usage
        exit "$EC_ENVIRONMENT"
        ;;
    esac
  done
}

collect_projects_json() {
  python3 - "$OTA_BUILDER_ROOT" "$OTA_BUILDS_DIR" "${OTA_PROJECTS_JSON:-$OTA_BUILDER_ROOT/config/projects.json}" "${OTA_BASE_URL:-}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root, ota_dir_s, projects_json_s, base_url = sys.argv[1:5]
base_url = base_url.rstrip("/")
sys.path.insert(0, str(Path(root) / "tools"))
from ota_index import collect_builds, load_projects_config

ota_dir = Path(ota_dir_s)
projects_json = Path(projects_json_s)
projects_config = load_projects_config(projects_json)
builds_data = collect_builds(ota_dir, projects_config)

projects = []
for project_id, meta in projects_config.items():
    path = meta.get("path", "")
    path_exists = Path(path).is_dir() if path else False
    builds = builds_data.get("projects", {}).get(project_id, {}).get("builds", [])
    latest_build = None
    if builds:
        b = builds[0]
        rel = b.get("path", "")
        install_path = f"{base_url}/{rel}/install.html" if base_url and rel else None
        latest_build = {
            "version": b.get("version"),
            "build_number": b.get("build_number"),
            "date": b.get("date"),
            "install_path": install_path,
        }
    projects.append(
        {
            "id": project_id,
            "display_name": meta.get("display_name", project_id),
            "path": path,
            "path_exists": path_exists,
            "latest_build": latest_build,
        }
    )

print(
    json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "projects": projects,
        }
    )
)
PY
}

collect_disk_json() {
  local threshold_mb avail_kb free_mb free_gb disk_ok
  threshold_mb="${OTA_STATUS_MIN_DISK_MB:-5000}"
  avail_kb="$(df -k "$OTA_BUILDS_DIR" | awk 'NR==2 {print $4}')"
  free_mb=$((avail_kb / 1024))
  free_gb="$(awk -v mb="$free_mb" 'BEGIN { printf "%.1f", mb / 1024 }')"
  disk_ok=true
  if [[ "$free_mb" -lt "$threshold_mb" ]]; then
    disk_ok=false
  fi
  jq -n \
    --argjson free_mb "$free_mb" \
    --arg free_gb "$free_gb" \
    --argjson threshold_mb "$threshold_mb" \
    --argjson ok "$disk_ok" \
    '{free_mb: $free_mb, free_gb: ($free_gb + " GB"), threshold_mb: $threshold_mb, ok: $ok}'
}

check_server() {
  local port url
  port="${OTA_PORT:-8765}"
  SERVER_URL="http://127.0.0.1:${port}/"
  set +e
  "$SCRIPT_DIR/serve_check.sh" >/dev/null 2>&1
  SERVER_EC=$?
  set -e
  SERVER_OK=false
  if [[ "$SERVER_EC" -eq 0 ]]; then
    SERVER_OK=true
  fi
}

server_json() {
  jq -n \
    --arg url "$SERVER_URL" \
    --argjson reachable "$SERVER_OK" \
    '{reachable: $reachable, url: $url}'
}

compute_exit_code() {
  local fail_server fail_disk
  fail_server="${OTA_STATUS_FAIL_ON_SERVER:-1}"
  fail_disk="${OTA_STATUS_FAIL_ON_DISK:-1}"

  if [[ "$fail_server" == "1" && "$SERVER_OK" == "false" ]]; then
    FINAL_EC="$EC_PUBLISH"
    return
  fi
  if [[ "$fail_disk" == "1" && "$DISK_OK" == "false" ]]; then
    FINAL_EC="$EC_ENVIRONMENT"
    return
  fi
  FINAL_EC="$EC_SUCCESS"
}

print_human() {
  local generated_at disk_line server_line path_label
  generated_at="$(jq -r '.generated_at' <<<"$STATUS_JSON")"

  echo "ios-ota-builder status — $generated_at"
  echo
  echo "Projects"

  while IFS= read -r line; do
    echo "$line"
  done < <(
    jq -r '.projects[] |
      "  \(.id)  \(.display_name)  path: " + (if .path_exists then "OK" else "MISSING" end) +
      (if .latest_build then
        "\n    latest: \(.latest_build.version // "?") (\(.latest_build.build_number // "?"))  \(.latest_build.date // "")" +
        (if .latest_build.install_path then "\n    install: \(.latest_build.install_path)" else "" end)
      else
        "\n    latest: (none)"
      end)' <<<"$STATUS_JSON"
  )

  echo
  disk_line="$(jq -r '"Disk: \(.disk.free_gb) free (min \(.disk.threshold_mb / 1024 | . * 10 | round / 10) GB)  " + (if .disk.ok then "OK" else "LOW" end)' <<<"$STATUS_JSON")"
  server_line="$(jq -r '"Server: \(.server.url)  " + (if .server.reachable then "OK" else "DOWN" end)' <<<"$STATUS_JSON")"
  echo "$disk_line"
  echo "$server_line"
}

main() {
  parse_args "$@"
  load_config

  local projects_payload disk_payload server_payload ok
  projects_payload="$(collect_projects_json)"
  disk_payload="$(collect_disk_json)"
  check_server
  server_payload="$(server_json)"

  DISK_OK="$(jq -r '.ok' <<<"$disk_payload")"

  STATUS_JSON="$(jq -n \
    --argjson projects "$(jq '.projects' <<<"$projects_payload")" \
    --arg generated_at "$(jq -r '.generated_at' <<<"$projects_payload")" \
    --argjson disk "$disk_payload" \
    --argjson server "$server_payload" \
  '{
    generated_at: $generated_at,
    ok: ($disk.ok and $server.reachable),
    projects: $projects,
    disk: $disk,
    server: $server
  }')"

  if [[ "$JSON_MODE" -eq 1 ]]; then
    echo "$STATUS_JSON"
  else
    print_human
  fi

  compute_exit_code
  exit "$FINAL_EC"
}

main "$@"
