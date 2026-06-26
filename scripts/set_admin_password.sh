#!/usr/bin/env bash
# Set admin username/password for dashboard login.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/tools/set_admin_password.py" "$@"
