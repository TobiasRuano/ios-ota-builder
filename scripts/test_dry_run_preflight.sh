#!/usr/bin/env bash
# F16 regression tests for dry-run preflight helpers.
# Runs on Linux without Xcode. Usage: ./scripts/test_dry_run_preflight.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

TMPDIR_TEST=""
MOCK_ROOT=""
pass_count=0
fail_count=0

pass() {
  pass_count=$((pass_count + 1))
  printf '  PASS: %s\n' "$1"
}

fail() {
  fail_count=$((fail_count + 1))
  printf '  FAIL: %s\n' "$1" >&2
}

assert_eq() {
  local actual="$1"
  local expected="$2"
  local label="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$label"
  else
    fail "$label (expected '$expected', got '$actual')"
  fi
}

cleanup() {
  if [[ -n "$TMPDIR_TEST" && -d "$TMPDIR_TEST" ]]; then
    rm -rf "$TMPDIR_TEST"
  fi
  if [[ -n "$MOCK_ROOT" && -d "$MOCK_ROOT" ]]; then
    rm -rf "$MOCK_ROOT"
  fi
}
trap cleanup EXIT

setup_mock_scripts() {
  local signing_ec="${1:-0}"
  local server_ec="${2:-0}"
  MOCK_ROOT="$(mktemp -d)"
  mkdir -p "$MOCK_ROOT/scripts"
  cat >"$MOCK_ROOT/scripts/verify_signing.sh" <<EOF
#!/usr/bin/env bash
exit ${signing_ec}
EOF
  cat >"$MOCK_ROOT/scripts/serve_check.sh" <<EOF
#!/usr/bin/env bash
exit ${server_ec}
EOF
  chmod +x "$MOCK_ROOT/scripts/verify_signing.sh" "$MOCK_ROOT/scripts/serve_check.sh"
  export OTA_BUILDER_ROOT="$MOCK_ROOT"
}

echo "=== F16 dry-run preflight tests ==="

echo "1. check_disk_space creates missing OTA_BUILDS_DIR root"
TMPDIR_TEST="$(mktemp -d)"
export OTA_BUILDS_DIR="$TMPDIR_TEST/OTA-Builds"
if [[ -d "$OTA_BUILDS_DIR" ]]; then
  fail "OTA_BUILDS_DIR should not exist before check"
else
  pass "OTA_BUILDS_DIR absent before check"
fi
check_disk_space 1
if [[ -d "$OTA_BUILDS_DIR" ]]; then
  pass "check_disk_space created OTA_BUILDS_DIR root"
else
  fail "check_disk_space created OTA_BUILDS_DIR root"
fi
build_dirs="$(find "$OTA_BUILDS_DIR" -mindepth 1 -maxdepth 2 2>/dev/null | wc -l | tr -d ' ')"
assert_eq "$build_dirs" "0" "no timestamped build subdirectories created"

echo "2. collect_disk_check_json returns valid structure"
disk_json="$(collect_disk_check_json 1)"
disk_ok="$(jq -r '.ok' <<<"$disk_json")"
free_mb="$(jq -r '.free_mb' <<<"$disk_json")"
threshold_mb="$(jq -r '.threshold_mb' <<<"$disk_json")"
assert_eq "$disk_ok" "true" "disk ok with low threshold"
if [[ "$free_mb" =~ ^[0-9]+$ && "$threshold_mb" == "1" ]]; then
  pass "disk json numeric fields"
else
  fail "disk json numeric fields (free_mb=$free_mb threshold_mb=$threshold_mb)"
fi

echo "3. print_preflight_json emits valid JSON on stdout"
export PROJECT_ID="test-app"
export DISPLAY_NAME="Test App"
preflight_json="$(print_preflight_json "ok" '[{"name":"config","status":"ok"}]' 2)"
assert_eq "$(jq -r '.status' <<<"$preflight_json")" "ok" "preflight status"
assert_eq "$(jq -r '.project' <<<"$preflight_json")" "test-app" "preflight project"
assert_eq "$(jq -r '.duration_seconds' <<<"$preflight_json")" "2" "preflight duration"
checks_len="$(jq '.checks | length' <<<"$preflight_json")"
assert_eq "$checks_len" "1" "preflight checks length"

echo "4. run_dry_run_preflight succeeds with passing mocks"
setup_mock_scripts 0 0
export OTA_BUILDS_DIR="$TMPDIR_TEST/OTA-Builds-pass"
mkdir -p "$OTA_BUILDS_DIR"
set +e
result_json="$(run_dry_run_preflight 2>/dev/null)"
preflight_ec=$?
set -e
assert_eq "$preflight_ec" "0" "preflight exit 0 when checks pass"
assert_eq "$(jq -r '.status' <<<"$result_json")" "ok" "overall status ok"
assert_eq "$(jq -r '.checks[] | select(.name=="signing") | .status' <<<"$result_json")" "ok" "signing check ok"
assert_eq "$(jq -r '.checks[] | select(.name=="server") | .status' <<<"$result_json")" "ok" "server check ok"

echo "5. run_dry_run_preflight fails when signing mock fails"
setup_mock_scripts 10 0
export OTA_BUILDS_DIR="$TMPDIR_TEST/OTA-Builds-sign-fail"
mkdir -p "$OTA_BUILDS_DIR"
set +e
result_json="$(run_dry_run_preflight 2>/dev/null)"
preflight_ec=$?
set -e
assert_eq "$preflight_ec" "10" "preflight exit 10 on signing failure"
assert_eq "$(jq -r '.status' <<<"$result_json")" "failed" "overall status failed on signing"
assert_eq "$(jq -r '.checks[] | select(.name=="signing") | .status' <<<"$result_json")" "failed" "signing check failed"

echo "6. run_dry_run_preflight warns but exits 0 when server mock fails"
setup_mock_scripts 0 60
export OTA_BUILDS_DIR="$TMPDIR_TEST/OTA-Builds-server-warn"
mkdir -p "$OTA_BUILDS_DIR"
set +e
result_json="$(run_dry_run_preflight 2>/dev/null)"
preflight_ec=$?
set -e
assert_eq "$preflight_ec" "0" "preflight exit 0 when only server fails"
assert_eq "$(jq -r '.status' <<<"$result_json")" "ok" "overall status ok with server warn"
assert_eq "$(jq -r '.checks[] | select(.name=="server") | .status' <<<"$result_json")" "warn" "server check warn"
assert_eq "$(jq -r '.checks[] | select(.name=="server") | .reachable' <<<"$result_json")" "false" "server not reachable"

echo ""
if [[ "$fail_count" -eq 0 ]]; then
  printf 'All %s tests passed.\n' "$pass_count"
  exit 0
fi
printf '%s passed, %s failed.\n' "$pass_count" "$fail_count" >&2
exit 1
