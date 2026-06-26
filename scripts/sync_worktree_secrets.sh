#!/usr/bin/env bash
# Symlink local secret files from base checkout into a git worktree.
# Usage: sync_worktree_secrets.sh <base_path> <worktree_path> <rel_path> [...]

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: sync_worktree_secrets.sh <base_path> <worktree_path> [rel_path ...]" >&2
  exit 1
fi

BASE_PATH="$(cd "$1" && pwd)"
WORKTREE_PATH="$(cd "$2" && pwd)"
shift 2

for rel in "$@"; do
  [[ -z "$rel" ]] && continue
  if [[ "$rel" == /* || "$rel" == *".."* ]]; then
    echo "WARN: skipping unsafe secrets_sync path: $rel" >&2
    continue
  fi
  src="$BASE_PATH/$rel"
  dest="$WORKTREE_PATH/$rel"
  if [[ ! -e "$src" ]]; then
    echo "WARN: secret not found in base checkout: $rel" >&2
    continue
  fi
  if [[ -e "$dest" ]]; then
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  ln -s "$src" "$dest"
  echo "Synced secret: $rel"
done
