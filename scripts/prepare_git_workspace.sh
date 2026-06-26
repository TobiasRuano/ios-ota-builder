#!/usr/bin/env bash
# Prepare app repo workspace for an OTA build (checkout, stash, or worktree).
# Usage: prepare_git_workspace.sh <project-id> [branch] [git_mode]
# Prints absolute workspace path on stdout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OTA_BUILDER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$OTA_BUILDER_ROOT/scripts/lib/common.sh"

usage() {
  cat >&2 <<EOF
Usage: prepare_git_workspace.sh <project-id> [branch] [git_mode]

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

fetch_remote() {
  local repo_path="$1"
  local remote="$2"
  if git -C "$repo_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$repo_path" fetch --prune "$remote" 2>&1 || log "Warning: git fetch $remote failed (continuing)"
  fi
}

checkout_branch() {
  local repo_path="$1"
  local branch="$2"
  local remote="$3"

  if [[ -z "$branch" ]]; then
    return 0
  fi

  local current
  current="$(git -C "$repo_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ "$current" == "$branch" ]]; then
    git -C "$repo_path" pull --ff-only "$remote" "$branch" 2>/dev/null || true
    return 0
  fi

  if git -C "$repo_path" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$repo_path" checkout "$branch"
  elif git -C "$repo_path" show-ref --verify --quiet "refs/remotes/$remote/$branch"; then
    git -C "$repo_path" checkout -B "$branch" "$remote/$branch"
  else
    log_error "Branch not found: $branch"
    exit "$EC_ENVIRONMENT"
  fi

  git -C "$repo_path" pull --ff-only "$remote" "$branch" 2>/dev/null || true
}

prepare_worktree() {
  local base_path="$1"
  local branch="$2"
  local remote="$3"
  local worktree_base="$4"

  if [[ -z "$worktree_base" ]]; then
    worktree_base="${HOME}/.ota-worktrees/${PROJECT_ID}"
  fi
  mkdir -p "$worktree_base"

  local slug wt_path
  if [[ -n "$branch" ]]; then
    slug="$(slugify_branch "$branch")"
  else
    slug="$(slugify_branch "$(git -C "$base_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)")"
  fi
  wt_path="$worktree_base/$slug"

  git -C "$base_path" worktree prune 2>/dev/null || true
  fetch_remote "$base_path" "$remote"

  if [[ -e "$wt_path/.git" || -f "$wt_path/.git" ]]; then
    log "Reusing existing worktree: $wt_path"
    if [[ -n "$branch" ]]; then
      git -C "$wt_path" checkout "$branch" 2>/dev/null || true
      git -C "$wt_path" pull --ff-only "$remote" "$branch" 2>/dev/null || true
    fi
  else
    if [[ -n "$branch" ]]; then
      if git -C "$base_path" show-ref --verify --quiet "refs/remotes/$remote/$branch"; then
        git -C "$base_path" worktree add -B "$branch" "$wt_path" "$remote/$branch"
      elif git -C "$base_path" show-ref --verify --quiet "refs/heads/$branch"; then
        git -C "$base_path" worktree add "$wt_path" "$branch"
      else
        log_error "Branch not found for worktree: $branch"
        exit "$EC_ENVIRONMENT"
      fi
    else
      local head_branch
      head_branch="$(git -C "$base_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
      git -C "$base_path" worktree add "$wt_path" "$head_branch"
    fi
  fi

  if [[ ${#SECRETS_SYNC[@]} -gt 0 ]]; then
    "$OTA_BUILDER_ROOT/scripts/sync_worktree_secrets.sh" \
      "$base_path" "$wt_path" "${SECRETS_SYNC[@]}"
  fi

  printf '%s\n' "$(cd "$wt_path" && pwd)"
}

main() {
  local project_id="${1:-}"
  local branch="${2:-}"
  local git_mode="${3:-auto}"

  if [[ -z "$project_id" ]]; then
    usage
    exit "$EC_ENVIRONMENT"
  fi

  load_config
  load_project "$project_id"

  local config_file="$OTA_BUILDER_ROOT/config/projects.json"
  GIT_REMOTE="$(jq -r --arg id "$project_id" '.projects[$id].git.remote // "origin"' "$config_file")"
  WORKTREE_BASE="$(jq -r --arg id "$project_id" '.projects[$id].git.worktree_base // ""' "$config_file")"
  mapfile -t SECRETS_SYNC < <(
    jq -r --arg id "$project_id" '.projects[$id].git.secrets_sync[]? // empty' "$config_file"
  )

  local base_path="$PROJECT_PATH"
  local mode
  mode="$(resolve_git_mode "$git_mode" "$base_path")"
  log "Git workspace mode: $mode (requested: ${git_mode:-auto})"

  case "$mode" in
    checkout)
      fetch_remote "$base_path" "$GIT_REMOTE"
      checkout_branch "$base_path" "$branch" "$GIT_REMOTE"
      printf '%s\n' "$(cd "$base_path" && pwd)"
      ;;
    stash_checkout)
      fetch_remote "$base_path" "$GIT_REMOTE"
      if [[ "$(repo_dirty_count "$base_path")" -gt 0 ]]; then
        git -C "$base_path" stash push -u -m "ota-build-$(date +%s)" || {
          log_error "git stash failed — resolve conflicts or use worktree mode"
          exit "$EC_ENVIRONMENT"
        }
      fi
      checkout_branch "$base_path" "$branch" "$GIT_REMOTE"
      printf '%s\n' "$(cd "$base_path" && pwd)"
      ;;
    worktree)
      prepare_worktree "$base_path" "$branch" "$GIT_REMOTE" "$WORKTREE_BASE"
      ;;
  esac
}

main "$@"
