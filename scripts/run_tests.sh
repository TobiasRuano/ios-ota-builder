#!/usr/bin/env bash
# Run automated tests (Python pytest + shell regression scripts).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! python3 -m pytest --version >/dev/null 2>&1; then
  echo "Installing dev dependencies..."
  python3 -m pip install -q -r requirements-dev.txt
fi

if [[ $# -gt 0 ]]; then
  exec python3 -m pytest "$@"
fi

echo "Running Python unit tests..."
python3 -m pytest

echo ""
echo "Running shell regression tests..."
for script in "$ROOT"/scripts/test_*.sh; do
  if [[ -x "$script" ]]; then
    echo "--- $(basename "$script") ---"
    "$script"
  fi
done
