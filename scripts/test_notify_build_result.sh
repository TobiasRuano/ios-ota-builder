#!/usr/bin/env bash
# F15 regression tests for notify_build_result() — webhook payload, guards, macOS message shape.
# Runs on Linux without a real build or osascript. Usage: ./scripts/test_notify_build_result.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TMPDIR_TEST=""
OSASCRIPT_LOG=""
WEBHOOK_BODY=""
WEBHOOK_HEADERS=""
MOCK_BIN=""

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

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    pass "$label"
  else
    fail "$label (expected to contain: $needle)"
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    pass "$label"
  else
    fail "$label (must not contain: $needle)"
  fi
}

assert_empty() {
  local value="$1"
  local label="$2"
  if [[ -z "$value" ]]; then
    pass "$label"
  else
    fail "$label (expected empty, got: $value)"
  fi
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

setup_mocks() {
  TMPDIR_TEST="$(mktemp -d)"
  OSASCRIPT_LOG="$TMPDIR_TEST/osascript.log"
  WEBHOOK_BODY="$TMPDIR_TEST/webhook_body.json"
  WEBHOOK_HEADERS="$TMPDIR_TEST/webhook_headers.txt"
  MOCK_BIN="$TMPDIR_TEST/bin"
  mkdir -p "$MOCK_BIN"

  cat >"$MOCK_BIN/osascript" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$OSASCRIPT_LOG"
exit 0
EOF

  cat >"$MOCK_BIN/curl" <<EOF
#!/usr/bin/env bash
: > "$WEBHOOK_HEADERS"
payload=""
secret=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    -H)
      printf '%s\n' "\$2" >> "$WEBHOOK_HEADERS"
      if [[ "\$2" == X-OTA-Webhook-Secret:* ]]; then
        secret="\${2#X-OTA-Webhook-Secret: }"
      fi
      shift 2
      ;;
    -d)
      payload="\$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf '%s' "\$payload" > "$WEBHOOK_BODY"
exit 0
EOF

  chmod +x "$MOCK_BIN/osascript" "$MOCK_BIN/curl"
  export PATH="$MOCK_BIN:$PATH"
  export OSASCRIPT_LOG WEBHOOK_BODY WEBHOOK_HEADERS
}

reset_capture() {
  : >"$OSASCRIPT_LOG"
  : >"$WEBHOOK_BODY"
  : >"$WEBHOOK_HEADERS"
}

reset_env() {
  unset OTA_NOTIFY_SKIP OTA_BUILD_ATTEMPTED OTA_NOTIFY OTA_WEBHOOK_URL OTA_WEBHOOK_SECRET
  unset START_EPOCH BUILD_PUBLISHED FAILED_STAGE PROJECT_ID DISPLAY_NAME BUILD_DIR_NAME
  export OTA_BUILDER_ROOT
}

load_notify_fn() {
  # shellcheck source=scripts/lib/common.sh
  source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"
}

cleanup() {
  if [[ -n "$TMPDIR_TEST" && -d "$TMPDIR_TEST" ]]; then
    rm -rf "$TMPDIR_TEST"
  fi
}

trap cleanup EXIT

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required" >&2
  exit 1
fi

setup_mocks
load_notify_fn

echo "F15 notify_build_result tests"
echo "=============================="

echo ""
echo "1. Success — macOS notification shape"
reset_env
reset_capture
export OTA_BUILD_ATTEMPTED=true
export OTA_NOTIFY=1
export PROJECT_ID=dev-quotes
export DISPLAY_NAME="Dev Quotes"
export BUILD_DIR_NAME=26-06-42
export BUILD_PUBLISHED=true
export START_EPOCH=$(($(date +%s) - 312))
notify_build_result 0
osascript_out="$(<"$OSASCRIPT_LOG")"
assert_contains "$osascript_out" "OTA build succeeded" "success title in osascript"
assert_contains "$osascript_out" "Dev Quotes build succeeded" "app name in macOS message"
assert_contains "$osascript_out" "5m 12s" "duration in macOS message"
assert_not_contains "$osascript_out" "token" "macOS message has no token"

echo ""
echo "2. Early failure — signing/preflight (before make_build_dir)"
reset_env
reset_capture
export OTA_BUILD_ATTEMPTED=true
export OTA_NOTIFY=1
export PROJECT_ID=dev-quotes
export DISPLAY_NAME="Dev Quotes"
export FAILED_STAGE=environment
export START_EPOCH=$(($(date +%s) - 4))
notify_build_result 10
osascript_out="$(<"$OSASCRIPT_LOG")"
assert_contains "$osascript_out" "OTA build failed" "failure title in osascript"
assert_contains "$osascript_out" "failed at environment" "stage environment in macOS message"

echo ""
echo "3. Late failure — archive and export stages"
reset_env
reset_capture
export OTA_BUILD_ATTEMPTED=true
export OTA_NOTIFY=1
export PROJECT_ID=dev-quotes
export DISPLAY_NAME="Dev Quotes"
export FAILED_STAGE=archive
notify_build_result 40
assert_contains "$(<"$OSASCRIPT_LOG")" "failed at archive" "archive stage in notification"

reset_capture
export FAILED_STAGE=export
notify_build_result 50
assert_contains "$(<"$OSASCRIPT_LOG")" "failed at export" "export stage in notification"

echo ""
echo "4. Webhook — OTA_NOTIFY=0, secret header, tokenless payload"
reset_env
reset_capture
export OTA_BUILD_ATTEMPTED=true
export OTA_NOTIFY=0
export OTA_WEBHOOK_URL=https://hooks.example.com/test
export OTA_WEBHOOK_SECRET=test-secret-123
export PROJECT_ID=dev-quotes
export DISPLAY_NAME="Dev Quotes"
export BUILD_DIR_NAME=26-06-42
export BUILD_PUBLISHED=true
export START_EPOCH=$(($(date +%s) - 100))
notify_build_result 0
assert_empty "$(<"$OSASCRIPT_LOG")" "no macOS notification when OTA_NOTIFY=0"
assert_contains "$(<"$WEBHOOK_HEADERS")" "X-OTA-Webhook-Secret: test-secret-123" "webhook secret header"
webhook_json="$(<"$WEBHOOK_BODY")"
assert_eq "$(jq -r '.status' <<<"$webhook_json")" "success" "webhook status success"
assert_eq "$(jq -r '.project' <<<"$webhook_json")" "dev-quotes" "webhook project"
assert_eq "$(jq -r '.display_name' <<<"$webhook_json")" "Dev Quotes" "webhook display_name"
assert_eq "$(jq -r '.install_path' <<<"$webhook_json")" "/dev-quotes/26-06-42/install.html" "webhook install_path without token"
assert_not_contains "$webhook_json" "token" "webhook payload has no token field"
assert_not_contains "$webhook_json" "install_url" "webhook payload has no install_url"
assert_not_contains "$webhook_json" "dashboard_url" "webhook payload has no dashboard_url"
assert_not_contains "$webhook_json" "?token=" "webhook payload has no query token"

reset_capture
export BUILD_PUBLISHED=false
export FAILED_STAGE=export
notify_build_result 50
webhook_json="$(<"$WEBHOOK_BODY")"
assert_eq "$(jq -r '.status' <<<"$webhook_json")" "failure" "webhook failure status"
assert_eq "$(jq -r '.stage' <<<"$webhook_json")" "export" "webhook failure stage"

echo ""
echo "5. Guards — no notification for usage errors"
reset_env
reset_capture
export OTA_NOTIFY=1
export OTA_WEBHOOK_URL=https://hooks.example.com/test
export OTA_BUILD_ATTEMPTED=false
notify_build_result 10
assert_empty "$(<"$OSASCRIPT_LOG")" "skip when OTA_BUILD_ATTEMPTED is not true"
assert_empty "$(<"$WEBHOOK_BODY")" "webhook skip when OTA_BUILD_ATTEMPTED is not true"

reset_capture
export OTA_BUILD_ATTEMPTED=true
export OTA_NOTIFY_SKIP=1
notify_build_result 0
assert_empty "$(<"$OSASCRIPT_LOG")" "skip when OTA_NOTIFY_SKIP=1"
assert_empty "$(<"$WEBHOOK_BODY")" "webhook skip when OTA_NOTIFY_SKIP=1"

reset_capture
unset OTA_NOTIFY_SKIP
export OTA_NOTIFY=0
unset OTA_WEBHOOK_URL
notify_build_result 0
assert_empty "$(<"$OSASCRIPT_LOG")" "skip when OTA_NOTIFY=0 and no webhook"
assert_empty "$(<"$WEBHOOK_BODY")" "no webhook when URL unset"

echo ""
echo "6. Security audit — notify_build_result source"
notify_src="$(sed -n '/^notify_build_result()/,/^}/p' "$OTA_BUILDER_ROOT/scripts/lib/common.sh")"
assert_not_contains "$notify_src" "ota_url" "notify_build_result does not call ota_url()"
assert_not_contains "$notify_src" "install_url" "notify_build_result does not reference install_url"
assert_not_contains "$notify_src" "dashboard_url" "notify_build_result does not reference dashboard_url"

echo ""
echo "=============================="
printf 'Results: %d passed, %d failed\n' "$pass_count" "$fail_count"
if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
echo "All F15 notify_build_result tests passed."
