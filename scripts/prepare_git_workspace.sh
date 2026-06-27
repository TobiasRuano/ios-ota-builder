#!/usr/bin/env bash
# Prepare app repo workspace for an OTA build (checkout, stash, or worktree).
# Usage: prepare_git_workspace.sh <project-id> [branch] [git_mode]
#        prepare_git_workspace.sh --sync-only [--json] [--strategy STRATEGY] [--verify-in-sync] <project-id> [branch] [git_mode]
# Prints absolute workspace path on stdout (or JSON with --sync-only --json).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

SYNC_ONLY=false
JSON_OUTPUT=false
VERIFY_IN_SYNC=false
STRATEGY=""
SYNC_STATE_FILE=".ota-sync-state.json"
FETCH_STATE_FILE=".ota-fetch-state.json"
SYNC_BEFORE=""
SYNC_AFTER=""

usage() {
  cat >&2 <<EOF
Usage: prepare_git_workspace.sh [options] <project-id> [branch] [git_mode]

Options:
  --sync-only       Sync workspace only (no path output unless --json)
  --json            Emit structured JSON on stdout (requires --sync-only)
  --strategy MODE   match_remote | fast_forward | recreate_worktree
  --verify-in-sync  Fail if workspace HEAD differs from remote branch tip

git_mode: auto | checkout | stash_checkout | worktree (default: auto)
EOF
}

slugify_branch() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-zA-Z0-9._-]+/-/g; s/^-|-$//g' | cut -c1-80
}

repo_dirty_count() {
  local repo_path="$1"
  local porcelain
  if ! git -C "$repo_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo 0
    return 0
  fi
  porcelain="$(git -C "$repo_path" status --porcelain 2>/dev/null || true)"
  if [[ -z "$porcelain" ]]; then
    echo 0
    return 0
  fi
  printf '%s\n' "$porcelain" | wc -l | tr -d ' '
}

resolve_git_mode() {
  local requested="$1"
  local base_path="$2"

  case "$requested" in
    auto)
      if [[ "$(repo_dirty_count "$base_path")" -gt 0 ]]; then
        echo "worktree"
      else
        echo "checkout"
      fi
      ;;
    checkout | stash_checkout | worktree)
      echo "$requested"
      ;;
    *)
      log_error "Invalid git_mode: $requested"
      exit "$EC_ENVIRONMENT"
      ;;
  esac
}

resolve_effective_branch() {
  local repo_path="$1"
  local branch="$2"
  if [[ -n "$branch" ]]; then
    printf '%s\n' "$branch"
    return 0
  fi
  git -C "$repo_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main"
}

validate_strategy() {
  local strategy="$1"
  case "$strategy" in
    match_remote | fast_forward | recreate_worktree) ;;
    *)
      log_error "Invalid sync strategy: $strategy"
      exit "$EC_ENVIRONMENT"
      ;;
  esac
}

write_fetch_state() {
  local repo_path="$1"
  local remote="$2"
  local now
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '{"at":"%s","remote":"%s"}\n' "$now" "$remote" >"$repo_path/$FETCH_STATE_FILE"
}

write_sync_state() {
  local repo_path="$1"
  local branch="$2"
  local remote="$3"
  local strategy="$4"
  local from_commit="$5"
  local to_commit="$6"
  local now
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  python3 - "$repo_path/$SYNC_STATE_FILE" "$now" "$branch" "$remote" "$strategy" "$from_commit" "$to_commit" <<'PY'
import json, sys
path, at, branch, remote, strategy, from_commit, to_commit = sys.argv[1:8]
payload = {
    "at": at,
    "branch": branch,
    "remote": remote,
    "strategy": strategy,
    "from_commit": from_commit,
    "to_commit": to_commit,
    "ok": True,
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")
PY
}

fetch_remote() {
  local repo_path="$1"
  local remote="$2"
  if git -C "$repo_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$repo_path" fetch --prune "$remote" >&2
    write_fetch_state "$repo_path" "$remote"
  fi
}

remote_branch_ref() {
  local remote="$1"
  local branch="$2"
  printf '%s/%s' "$remote" "$branch"
}

ensure_branch_checked_out() {
  local repo_path="$1"
  local branch="$2"
  local remote="$3"
  local remote_ref
  remote_ref="$(remote_branch_ref "$remote" "$branch")"

  local current
  current="$(git -C "$repo_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ "$current" == "$branch" ]]; then
    return 0
  fi

  if git -C "$repo_path" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$repo_path" checkout "$branch" >&2
  elif git -C "$repo_path" show-ref --verify --quiet "refs/remotes/$remote_ref"; then
    git -C "$repo_path" checkout -B "$branch" "$remote_ref" >&2
  else
    log_error "Branch not found: $branch (no refs/heads/$branch or refs/remotes/$remote_ref)"
    exit "$EC_ENVIRONMENT"
  fi
}

sync_branch_in_repo() {
  local repo_path="$1"
  local branch="$2"
  local remote="$3"
  local strategy="$4"
  local remote_ref
  remote_ref="$(remote_branch_ref "$remote" "$branch")"

  if ! git -C "$repo_path" show-ref --verify --quiet "refs/remotes/$remote_ref"; then
    log_error "Remote branch not found: $remote_ref — run git fetch first"
    exit "$EC_ENVIRONMENT"
  fi

  ensure_branch_checked_out "$repo_path" "$branch" "$remote"

  local before after
  before="$(git -C "$repo_path" rev-parse HEAD)"
  local effective_strategy="$strategy"
  if [[ "$effective_strategy" == "recreate_worktree" ]]; then
    effective_strategy="match_remote"
    log "recreate_worktree not applicable in checkout mode — using match_remote" >&2
  fi

  case "$effective_strategy" in
    match_remote)
      git -C "$repo_path" reset --hard "$remote_ref" >&2
      ;;
    fast_forward)
      if ! git -C "$repo_path" merge --ff-only "$remote_ref" >&2; then
        log_error "Fast-forward sync failed for $branch (branch diverged from $remote_ref)"
        exit "$EC_ENVIRONMENT"
      fi
      ;;
  esac

  after="$(git -C "$repo_path" rev-parse HEAD)"
  write_sync_state "$repo_path" "$branch" "$remote" "$strategy" "$before" "$after"
  SYNC_BEFORE="$before"
  SYNC_AFTER="$after"
  printf '%s\n' "$before"
  printf '%s\n' "$after"
}

verify_in_sync_with_remote() {
  local repo_path="$1"
  local branch="$2"
  local remote="$3"
  local remote_ref
  remote_ref="$(remote_branch_ref "$remote" "$branch")"

  if ! git -C "$repo_path" show-ref --verify --quiet "refs/remotes/$remote_ref"; then
    log_error "Cannot verify sync: remote branch $remote_ref not found"
    exit "$EC_ENVIRONMENT"
  fi

  local head remote_sha
  head="$(git -C "$repo_path" rev-parse HEAD)"
  remote_sha="$(git -C "$repo_path" rev-parse "$remote_ref")"
  if [[ "$head" != "$remote_sha" ]]; then
    log_error "Workspace not in sync with $remote_ref (HEAD=$head, remote=$remote_sha)"
    exit "$EC_ENVIRONMENT"
  fi
}

remove_worktree_path() {
  local base_path="$1"
  local wt_path="$2"
  if [[ -e "$wt_path/.git" || -f "$wt_path/.git" ]]; then
    git -C "$base_path" worktree remove --force "$wt_path" >&2 2>/dev/null || rm -rf "$wt_path"
  elif [[ -d "$wt_path" ]]; then
    rm -rf "$wt_path"
  fi
  git -C "$base_path" worktree prune >&2 2>/dev/null || true
}

create_worktree_from_remote() {
  local base_path="$1"
  local wt_path="$2"
  local branch="$3"
  local remote="$4"
  local remote_ref
  remote_ref="$(remote_branch_ref "$remote" "$branch")"

  if git -C "$base_path" show-ref --verify --quiet "refs/remotes/$remote_ref"; then
    git -C "$base_path" worktree add -B "$branch" "$wt_path" "$remote_ref" >&2
  elif git -C "$base_path" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$base_path" worktree add "$wt_path" "$branch" >&2
  else
    log_error "Branch not found for worktree: $branch"
    exit "$EC_ENVIRONMENT"
  fi
}

prepare_worktree() {
  local base_path="$1"
  local branch="$2"
  local remote="$3"
  local worktree_base="$4"
  local strategy="$5"

  if [[ -z "$worktree_base" ]]; then
    worktree_base="${HOME}/.ota-worktrees/${PROJECT_ID}"
  fi
  mkdir -p "$worktree_base"

  local effective_branch slug wt_path before after
  effective_branch="$(resolve_effective_branch "$base_path" "$branch")"
  slug="$(slugify_branch "$effective_branch")"
  wt_path="$worktree_base/$slug"

  git -C "$base_path" worktree prune >&2 2>/dev/null || true
  fetch_remote "$base_path" "$remote"

  if [[ "$strategy" == "recreate_worktree" ]] && [[ -e "$wt_path/.git" || -f "$wt_path/.git" || -d "$wt_path" ]]; then
    log "Recreating worktree: $wt_path" >&2
    remove_worktree_path "$base_path" "$wt_path"
  fi

  if [[ -e "$wt_path/.git" || -f "$wt_path/.git" ]]; then
    log "Reusing existing worktree: $wt_path" >&2
    if [[ -n "$effective_branch" ]]; then
      ensure_branch_checked_out "$wt_path" "$effective_branch" "$remote"
    fi
  else
    create_worktree_from_remote "$base_path" "$wt_path" "$effective_branch" "$remote"
  fi

  before="$(git -C "$wt_path" rev-parse HEAD)"
  if [[ -n "$effective_branch" ]]; then
    sync_branch_in_repo "$wt_path" "$effective_branch" "$remote" "$strategy" >/dev/null
    after="$(git -C "$wt_path" rev-parse HEAD)"
  else
    after="$before"
  fi

  if [[ ${#SECRETS_SYNC[@]} -gt 0 ]]; then
    "$OTA_BUILDER_ROOT/scripts/sync_worktree_secrets.sh" \
      "$base_path" "$wt_path" "${SECRETS_SYNC[@]}"
  fi

  SYNC_BEFORE="$before"
  SYNC_AFTER="$after"
  printf '%s\n' "$(cd "$wt_path" && pwd)"
}

checkout_branch() {
  local repo_path="$1"
  local branch="$2"
  local remote="$3"
  local strategy="$4"

  local effective_branch
  effective_branch="$(resolve_effective_branch "$repo_path" "$branch")"
  if [[ -z "$effective_branch" || "$effective_branch" == "HEAD" ]]; then
    log_error "Could not resolve branch for sync"
    exit "$EC_ENVIRONMENT"
  fi

  sync_branch_in_repo "$repo_path" "$effective_branch" "$remote" "$strategy" >/dev/null
}

emit_sync_json() {
  local workspace_path="$1"
  local branch="$2"
  local remote="$3"
  local strategy="$4"
  local git_mode_resolved="$5"
  local before="${SYNC_BEFORE:-}"
  local after="${SYNC_AFTER:-}"

  if [[ -z "$after" && -n "$workspace_path" ]]; then
    after="$(git -C "$workspace_path" rev-parse HEAD 2>/dev/null || echo "")"
  fi
  if [[ -z "$before" ]]; then
    before="$after"
  fi

  python3 - "$workspace_path" "$branch" "$remote" "$strategy" "$git_mode_resolved" "$before" "$after" <<'PY'
import json, sys
workspace_path, branch, remote, strategy, git_mode, before, after = sys.argv[1:8]
print(json.dumps({
    "ok": True,
    "workspace_path": workspace_path,
    "branch": branch,
    "remote": remote,
    "strategy": strategy,
    "git_mode": git_mode,
    "before": {"commit": before[:7] if before else "", "commit_full": before},
    "after": {"commit": after[:7] if after else "", "commit_full": after},
    "sync_status": "in_sync" if before == after else "updated",
}, indent=2))
PY
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sync-only)
        SYNC_ONLY=true
        shift
        ;;
      --json)
        JSON_OUTPUT=true
        shift
        ;;
      --strategy)
        STRATEGY="${2:-}"
        shift 2
        ;;
      --verify-in-sync)
        VERIFY_IN_SYNC=true
        shift
        ;;
      -h | --help)
        usage
        exit 0
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
        break
        ;;
    esac
  done

  if [[ "$JSON_OUTPUT" == true && "$SYNC_ONLY" != true ]]; then
    log_error "--json requires --sync-only"
    exit "$EC_ENVIRONMENT"
  fi

  PROJECT_ID="${1:-}"
  BRANCH="${2:-}"
  GIT_MODE="${3:-auto}"
}

main() {
  parse_args "$@"

  if [[ -z "$PROJECT_ID" ]]; then
    usage
    exit "$EC_ENVIRONMENT"
  fi

  load_config
  load_project "$PROJECT_ID"

  local config_file="$OTA_BUILDER_ROOT/config/projects.json"
  GIT_REMOTE="$(jq -r --arg id "$PROJECT_ID" '.projects[$id].git.remote // "origin"' "$config_file")"
  WORKTREE_BASE="$(jq -r --arg id "$PROJECT_ID" '.projects[$id].git.worktree_base // ""' "$config_file")"
  DEFAULT_SYNC_STRATEGY="$(jq -r --arg id "$PROJECT_ID" '.projects[$id].git.default_sync_strategy // "match_remote"' "$config_file")"
  SECRETS_SYNC=()
  while IFS= read -r _secret; do
    [[ -n "$_secret" ]] && SECRETS_SYNC+=("$_secret")
  done < <(jq -r --arg id "$PROJECT_ID" '.projects[$id].git.secrets_sync[]? // empty' "$config_file")

  if [[ -z "$STRATEGY" ]]; then
    STRATEGY="$DEFAULT_SYNC_STRATEGY"
  fi
  validate_strategy "$STRATEGY"

  local base_path="$PROJECT_PATH"
  local mode effective_branch workspace_path=""
  mode="$(resolve_git_mode "$GIT_MODE" "$base_path")"
  effective_branch="$(resolve_effective_branch "$base_path" "$BRANCH")"
  log "Git workspace mode: $mode (requested: ${GIT_MODE:-auto}), sync: $STRATEGY" >&2

  case "$mode" in
    checkout)
      fetch_remote "$base_path" "$GIT_REMOTE"
      checkout_branch "$base_path" "$BRANCH" "$GIT_REMOTE" "$STRATEGY"
      workspace_path="$(cd "$base_path" && pwd)"
      ;;
    stash_checkout)
      fetch_remote "$base_path" "$GIT_REMOTE"
      if [[ "$(repo_dirty_count "$base_path")" -gt 0 ]]; then
        git -C "$base_path" stash push -u -m "ota-build-$(date +%s)" >&2 || {
          log_error "git stash failed — resolve conflicts or use worktree mode"
          exit "$EC_ENVIRONMENT"
        }
      fi
      checkout_branch "$base_path" "$BRANCH" "$GIT_REMOTE" "$STRATEGY"
      workspace_path="$(cd "$base_path" && pwd)"
      ;;
    worktree)
      workspace_path="$(prepare_worktree "$base_path" "$BRANCH" "$GIT_REMOTE" "$WORKTREE_BASE" "$STRATEGY")"
      ;;
  esac

  if [[ "$VERIFY_IN_SYNC" == true && -n "$effective_branch" ]]; then
    verify_in_sync_with_remote "$workspace_path" "$effective_branch" "$GIT_REMOTE"
  fi

  if [[ "$SYNC_ONLY" == true ]]; then
    if [[ "$JSON_OUTPUT" == true ]]; then
      emit_sync_json "$workspace_path" "$effective_branch" "$GIT_REMOTE" "$STRATEGY" "$mode"
    fi
    exit 0
  fi

  printf '%s\n' "$workspace_path"
}

main "$@"
