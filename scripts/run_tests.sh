#!/usr/bin/env bash
# Run Python unit tests (Linux and macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! python3 -m pytest --version >/dev/null 2>&1; then
  echo "Installing dev dependencies..."
  python3 -m pip install -q -r requirements-dev.txt
fi

exec python3 -m pytest "$@"
