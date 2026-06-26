#!/usr/bin/env bash
# Smoke tests for F14 per-project build lock (runs on Linux/macOS without Xcode).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

export OTA_BUILDS_DIR="$TEST_ROOT/builds"
mkdir -p "$OTA_BUILDS_DIR"

pass=0
fail=0

assert() {
  local description="$1"
  local result="${2:-1}"
  if [[ "$result" -eq 0 ]]; then
    printf 'PASS: %s\n' "$description"
    pass=$((pass + 1))
  else
    printf 'FAIL: %s\n' "$description" >&2
    fail=$((fail + 1))
  fi
}

reset_lock_state() {
  BUILD_LOCK_ACQUIRED=false
  unset BUILD_LOCK_DIR || true
  rm -rf "$OTA_BUILDS_DIR"/.lock-*
}

# --- different project-ids do not conflict ---
reset_lock_state
PROJECT_ID="proj-a"
acquire_build_lock
lock_a="$(build_lock_dir)"
PROJECT_ID="proj-b"
acquire_build_lock
lock_b="$(build_lock_dir)"
assert "different project-ids acquire separate locks" "$(
  [[ -d "$lock_a" && -d "$lock_b" && "$lock_a" != "$lock_b" ]]; echo $?
)"
PROJECT_ID="proj-b"
release_build_lock
PROJECT_ID="proj-a"
release_build_lock

# --- fail mode rejects second holder ---
reset_lock_state
PROJECT_ID="my-app"
export OTA_BUILD_LOCK=fail
acquire_build_lock
(
  export PROJECT_ID="my-app" OTA_BUILD_LOCK=fail
  acquire_build_lock 2>/dev/null
) && second_acquired=0 || second_acquired=1
assert "fail mode blocks second build for same project-id" "$(
  [[ "$second_acquired" -eq 1 ]]; echo $?
)"
release_build_lock

# --- wait mode acquires after release ---
reset_lock_state
PROJECT_ID="my-app"
export OTA_BUILD_LOCK=wait OTA_BUILD_LOCK_TIMEOUT=5
acquire_build_lock
(
  export PROJECT_ID="my-app" OTA_BUILD_LOCK=wait OTA_BUILD_LOCK_TIMEOUT=5
  sleep 0.3
  acquire_build_lock
  release_build_lock
) &
wait_pid=$!
sleep 0.05
release_build_lock
if wait "$wait_pid"; then
  waited_ok=0
else
  waited_ok=1
fi
assert "wait mode acquires lock after first holder releases" "$waited_ok"

# --- release on exit path ---
reset_lock_state
PROJECT_ID="my-app"
export OTA_BUILD_LOCK=fail
acquire_build_lock
lock_dir="$(build_lock_dir)"
release_build_lock
assert "release_build_lock removes lock directory" "$(
  [[ ! -d "$lock_dir" ]]; echo $?
)"

# --- stale lock cleanup ---
reset_lock_state
PROJECT_ID="my-app"
stale_dir="$(build_lock_dir)"
mkdir -p "$stale_dir"
printf '999999\n' >"$stale_dir/pid"
export OTA_BUILD_LOCK=fail
acquire_build_lock
assert "stale lock with dead pid is replaced" "$(
  [[ -f "$stale_dir/pid" && "$(tr -d '[:space:]' <"$stale_dir/pid")" == "$$" ]]; echo $?
)"
release_build_lock

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
