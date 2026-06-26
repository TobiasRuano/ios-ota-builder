#!/usr/bin/env bash
# Print eval-able shell snippet: OTA_BUILDER_ROOT + ota-* aliases.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Escape single quotes for safe embedding in single-quoted shell strings.
ROOT_ESC="${ROOT//\'/\'\\\'\'}"

cat <<EOF
export OTA_BUILDER_ROOT='$ROOT_ESC'
alias ota-build='\$OTA_BUILDER_ROOT/agent_build_ota.sh'
alias ota-install='\$OTA_BUILDER_ROOT/scripts/print_install_url.sh'
alias ota-dashboard='\$OTA_BUILDER_ROOT/scripts/print_dashboard_url.sh'
alias ota-status='\$OTA_BUILDER_ROOT/scripts/ota_status.sh'
EOF
