#!/usr/bin/env bash
# F17 regression tests for emit_build_stage(), write_build_status(), effective_build_stage().
# Runs on Linux without a real Xcode build. Usage: ./scripts/test_build_stage.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

TMPDIR_TEST=""
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

assert_file_missing() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    pass "$label"
  else
    fail "$label (file exists: $path)"
  fi
}

cleanup() {
  if [[ -n "$TMPDIR_TEST" && -d "$TMPDIR_TEST" ]]; then
    rm -rf "$TMPDIR_TEST"
  fi
}
trap cleanup EXIT

setup() {
  TMPDIR_TEST="$(mktemp -d)"
  export PROJECT_ID="test-app"
  export DISPLAY_NAME="Test App"
  export GIT_BRANCH="main"
  export GIT_COMMIT="abc1234"
  export BUILD_DIR_NAME="26-06-test"
  export BUILD_OUTPUT_DIR="$TMPDIR_TEST/build-out"
  mkdir -p "$BUILD_OUTPUT_DIR"
  export START_EPOCH="$(date +%s)"
  CURRENT_BUILD_STAGE=""
  export CURRENT_BUILD_STAGE
  FAILED_STAGE=""
  export FAILED_STAGE
  unset OTA_BUILD_STATUS BUILD_STATUS_STARTED_AT
}

echo "=== F17 build stage tests ==="

echo "1. emit_build_stage writes machine-parseable stderr marker"
setup
emit_build_stage resolving_spm 2>"$TMPDIR_TEST/stage.err"
stderr_out="$(<"$TMPDIR_TEST/stage.err")"
assert_eq "$stderr_out" "[stage] resolving_spm" "stderr marker format"
assert_eq "$CURRENT_BUILD_STAGE" "resolving_spm" "CURRENT_BUILD_STAGE updated"

echo "2. build.status opt-in disabled by default"
setup
emit_build_stage archiving >/dev/null 2>&1
assert_file_missing "$BUILD_OUTPUT_DIR/build.status" "no build.status without OTA_BUILD_STATUS"

echo "3. build.status written when OTA_BUILD_STATUS=1"
setup
export OTA_BUILD_STATUS=1
emit_build_stage archiving >/dev/null 2>&1
if [[ -f "$BUILD_OUTPUT_DIR/build.status" ]]; then
  pass "build.status file created"
  status="$(jq -r '.status' "$BUILD_OUTPUT_DIR/build.status")"
  stage="$(jq -r '.stage' "$BUILD_OUTPUT_DIR/build.status")"
  project="$(jq -r '.project' "$BUILD_OUTPUT_DIR/build.status")"
  assert_eq "$status" "in_progress" "build.status status"
  assert_eq "$stage" "archiving" "build.status stage"
  assert_eq "$project" "test-app" "build.status project"
else
  fail "build.status file created"
fi
write_build_status "failure" "archiving"
failure_stage="$(jq -r '.stage' "$BUILD_OUTPUT_DIR/build.status")"
failure_status="$(jq -r '.status' "$BUILD_OUTPUT_DIR/build.status")"
assert_eq "$failure_status" "failure" "build.status failure status"
assert_eq "$failure_stage" "archiving" "build.status failure stage"

echo "4. effective_build_stage prefers FAILED_STAGE then CURRENT_BUILD_STAGE"
setup
CURRENT_BUILD_STAGE="exporting"
export CURRENT_BUILD_STAGE
assert_eq "$(effective_build_stage)" "exporting" "CURRENT_BUILD_STAGE when FAILED_STAGE empty"
FAILED_STAGE="environment"
export FAILED_STAGE
assert_eq "$(effective_build_stage)" "environment" "FAILED_STAGE takes precedence"

echo "5. write_summary_json success keeps stage null"
setup
write_summary_json "success" "" 12 "" "" "" "1.0" "42" "" "" "Release" 0
summary_stage="$(jq -r '.stage' "$BUILD_OUTPUT_DIR/summary.json")"
if [[ "$summary_stage" == "null" ]]; then
  pass "success summary stage is null"
else
  fail "success summary stage is null (got: $summary_stage)"
fi

echo "6. write_summary_json failure records fine-grained stage"
setup
CURRENT_BUILD_STAGE="resolving_spm"
export CURRENT_BUILD_STAGE
write_summary_json "failure" "$(effective_build_stage)" 5 "" "" "" "" "" "" "" "Release" 0
failure_summary_stage="$(jq -r '.stage' "$BUILD_OUTPUT_DIR/summary.json")"
assert_eq "$failure_summary_stage" "resolving_spm" "failure summary stage"

echo ""
if [[ "$fail_count" -eq 0 ]]; then
  printf 'All %s tests passed.\n' "$pass_count"
  exit 0
fi
printf '%s passed, %s failed.\n' "$pass_count" "$fail_count" >&2
exit 1
