"""Git introspection and operations for dashboard build triggers."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from build_jobs import GIT_MODES, BuildJobError, PROJECT_ID_RE, SYNC_STRATEGIES


class GitApiError(ValueError):
    pass


SYNC_STATE_FILE = ".ota-sync-state.json"
FETCH_STATE_FILE = ".ota-fetch-state.json"
_BRANCH_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _run_git(repo_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo_path), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GitApiError(detail or f"git failed: {' '.join(args)}")
    return result


def _is_git_repo(repo_path: Path) -> bool:
    result = _run_git(repo_path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def validate_project_id(project_id: str) -> None:
    if not PROJECT_ID_RE.match(project_id):
        raise GitApiError("invalid project_id")


def get_project_repo_path(projects_json: Path, project_id: str) -> Path:
    validate_project_id(project_id)
    if not projects_json.is_file():
        raise GitApiError("projects.json not found")
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    projects = config.get("projects", {})
    if project_id not in projects:
        raise GitApiError("unknown project_id")
    path = projects[project_id].get("path", "")
    if not path:
        raise GitApiError("project path not configured")
    repo_path = Path(path).expanduser().resolve()
    if not repo_path.is_dir():
        raise GitApiError(f"project path not found: {repo_path}")
    return repo_path


def get_git_config(projects_json: Path, project_id: str) -> dict:
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    project = config.get("projects", {}).get(project_id, {})
    git_cfg = project.get("git") or {}
    if not isinstance(git_cfg, dict):
        git_cfg = {}
    secrets_sync = git_cfg.get("secrets_sync") or []
    if not isinstance(secrets_sync, list):
        secrets_sync = []
    return {
        "remote": str(git_cfg.get("remote") or "origin"),
        "worktree_base": str(git_cfg.get("worktree_base") or "").strip(),
        "default_mode": str(git_cfg.get("default_mode") or "auto"),
        "default_sync_strategy": str(git_cfg.get("default_sync_strategy") or "match_remote"),
        "require_sync_before_build": bool(git_cfg.get("require_sync_before_build", True)),
        "allow_stale_build": bool(git_cfg.get("allow_stale_build", False)),
        "secrets_sync": [str(s) for s in secrets_sync if s],
    }


def git_status(repo_path: Path) -> dict:
    if not _is_git_repo(repo_path):
        return {
            "is_git_repo": False,
            "branch": "unknown",
            "commit": "unknown",
            "dirty_count": 0,
            "dirty_files": [],
            "has_conflicts": False,
        }

    branch = _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    commit = _run_git(repo_path, "rev-parse", "--short", "HEAD").stdout.strip()
    porcelain = _run_git(repo_path, "status", "--porcelain").stdout
    lines = [line for line in porcelain.splitlines() if line.strip()]
    dirty_files = [line[3:] if len(line) > 3 else line for line in lines]

    has_conflicts = any(
        line.startswith(("UU ", "AA ", "DD ", "AU ", "UA ", "DU ", "UD "))
        for line in lines
    )
    if (repo_path / ".git" / "MERGE_HEAD").is_file():
        has_conflicts = True

    return {
        "is_git_repo": True,
        "branch": branch,
        "commit": commit,
        "dirty_count": len(lines),
        "dirty_files": dirty_files[:20],
        "has_conflicts": has_conflicts,
    }


def list_branches(repo_path: Path, *, remote: str = "origin") -> dict:
    if not _is_git_repo(repo_path):
        return {"local": [], "remote": [], "current": "unknown"}

    current = _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    local_raw = _run_git(repo_path, "branch", "--format=%(refname:short)").stdout
    local = sorted({b.strip() for b in local_raw.splitlines() if b.strip() and b.strip() != "HEAD"})

    remote_raw = _run_git(repo_path, "branch", "-r", "--format=%(refname:short)").stdout
    remote_branches: list[str] = []
    for line in remote_raw.splitlines():
        name = line.strip()
        if not name or "HEAD" in name:
            continue
        if name.startswith(f"{remote}/"):
            remote_branches.append(name[len(remote) + 1 :])
    remote_branches = sorted(set(remote_branches))

    return {"local": local, "remote": remote_branches, "current": current}


def git_fetch(repo_path: Path, *, remote: str = "origin") -> dict:
    if not _is_git_repo(repo_path):
        raise GitApiError("not a git repository")
    _run_git(repo_path, "fetch", "--prune", remote)
    from datetime import datetime, timezone

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (repo_path / FETCH_STATE_FILE).write_text(
        json.dumps({"at": fetched_at, "remote": remote}) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "remote": remote, "fetched_at": fetched_at}


def slugify_branch(branch: str) -> str:
    slug = _BRANCH_SLUG_RE.sub("-", branch.lower()).strip("-")
    return slug[:80]


def resolve_git_mode(requested: str, base_path: Path) -> str:
    mode = requested.strip() or "auto"
    if mode != "auto":
        if mode not in GIT_MODES:
            raise GitApiError(f"invalid git_mode: {mode}")
        return mode
    status = git_status(base_path)
    if status["dirty_count"] > 0:
        return "worktree"
    return "checkout"


def resolve_effective_branch(repo_path: Path, branch: str) -> str:
    branch = branch.strip()
    if branch:
        return branch
    if not _is_git_repo(repo_path):
        return "main"
    return _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"


def resolve_build_workspace_path(
    base_path: Path,
    *,
    project_id: str,
    branch: str,
    git_mode: str,
    worktree_base: str,
) -> Path:
    mode = resolve_git_mode(git_mode, base_path)
    if mode in {"checkout", "stash_checkout"}:
        return base_path
    wt_root = Path(worktree_base).expanduser() if worktree_base else Path.home() / ".ota-worktrees" / project_id
    effective = resolve_effective_branch(base_path, branch)
    return wt_root / slugify_branch(effective)


def _commit_details(repo_path: Path, ref: str) -> dict | None:
    if not ref:
        return None
    result = _run_git(
        repo_path,
        "rev-parse",
        "--short",
        ref,
        check=False,
    )
    if result.returncode != 0:
        return None
    short = result.stdout.strip()
    full = _run_git(repo_path, "rev-parse", ref, check=False).stdout.strip()
    subject = _run_git(
        repo_path,
        "log",
        "-1",
        "--format=%s",
        ref,
        check=False,
    ).stdout.strip()
    return {"commit": short, "commit_full": full, "subject": subject}


def _read_json_state(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def compare_with_remote(repo_path: Path, *, branch: str, remote: str) -> dict:
    remote_ref = f"{remote}/{branch}"
    local = _commit_details(repo_path, "HEAD")
    remote_commit = _commit_details(repo_path, remote_ref)

    if remote_commit is None:
        return {
            "sync_status": "unknown",
            "commits_ahead": 0,
            "commits_behind": 0,
            "local": local,
            "remote": None,
        }

    if local is None:
        return {
            "sync_status": "unknown",
            "commits_ahead": 0,
            "commits_behind": 0,
            "local": None,
            "remote": remote_commit,
        }

    if local["commit_full"] == remote_commit["commit_full"]:
        return {
            "sync_status": "in_sync",
            "commits_ahead": 0,
            "commits_behind": 0,
            "local": local,
            "remote": remote_commit,
        }

    ahead = _run_git(
        repo_path,
        "rev-list",
        "--count",
        f"{remote_ref}..HEAD",
        check=False,
    )
    behind = _run_git(
        repo_path,
        "rev-list",
        "--count",
        f"HEAD..{remote_ref}",
        check=False,
    )
    commits_ahead = int(ahead.stdout.strip() or "0") if ahead.returncode == 0 else 0
    commits_behind = int(behind.stdout.strip() or "0") if behind.returncode == 0 else 0

    if commits_ahead and commits_behind:
        status = "diverged"
    elif commits_behind:
        status = "behind"
    elif commits_ahead:
        status = "ahead"
    else:
        status = "unknown"

    return {
        "sync_status": status,
        "commits_ahead": commits_ahead,
        "commits_behind": commits_behind,
        "local": local,
        "remote": remote_commit,
    }


def last_build_commit(ota_dir: Path, project_id: str) -> dict | None:
    project_builds = ota_dir / project_id
    if not project_builds.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for build_dir in project_builds.iterdir():
        if not build_dir.is_dir():
            continue
        summary_path = build_dir / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if summary.get("status") != "success":
            continue
        try:
            mtime = summary_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, summary))
    if not candidates:
        return None
    _, latest = max(candidates, key=lambda item: item[0])
    commit = latest.get("commit") or ""
    commit_full = latest.get("commit_full") or commit
    return {
        "commit": commit,
        "commit_full": commit_full,
        "build_dir": latest.get("dir") or latest.get("build_label") or "",
    }


def workspace_status(
    projects_json: Path,
    project_id: str,
    *,
    branch: str = "",
    git_mode: str = "auto",
    strategy: str = "",
    ota_dir: Path | None = None,
) -> dict:
    validate_project_id(project_id)
    git_cfg = get_git_config(projects_json, project_id)
    base_path = get_project_repo_path(projects_json, project_id)
    mode = resolve_git_mode(git_mode, base_path)
    effective_branch = resolve_effective_branch(base_path, branch)
    workspace_path = resolve_build_workspace_path(
        base_path,
        project_id=project_id,
        branch=branch,
        git_mode=git_mode,
        worktree_base=git_cfg["worktree_base"],
    )

    base_status = git_status(base_path)
    workspace_exists = workspace_path.is_dir() and _is_git_repo(workspace_path)
    workspace_status_data = git_status(workspace_path) if workspace_exists else {
        "is_git_repo": False,
        "branch": effective_branch,
        "commit": "unknown",
        "dirty_count": 0,
        "dirty_files": [],
        "has_conflicts": False,
    }

    fetch_state = _read_json_state(base_path / FETCH_STATE_FILE)
    sync_state = _read_json_state(
        (workspace_path if workspace_exists else base_path) / SYNC_STATE_FILE
    )

    remote_info: dict | None = None
    comparison = {
        "sync_status": "unknown",
        "commits_ahead": 0,
        "commits_behind": 0,
    }
    if _is_git_repo(base_path):
        remote_ref = f"{git_cfg['remote']}/{effective_branch}"
        remote_info = _commit_details(base_path, remote_ref)
        if workspace_exists:
            comparison = compare_with_remote(
                workspace_path,
                branch=effective_branch,
                remote=git_cfg["remote"],
            )
        elif remote_info:
            comparison = {
                "sync_status": "unknown",
                "commits_ahead": 0,
                "commits_behind": 0,
                "local": None,
                "remote": remote_info,
            }

    preview_strategy = strategy.strip() or git_cfg["default_sync_strategy"]
    if preview_strategy not in SYNC_STRATEGIES:
        preview_strategy = git_cfg["default_sync_strategy"]
    preview_after = remote_info["commit_full"] if remote_info else ""
    if comparison.get("sync_status") == "diverged" and preview_strategy == "fast_forward":
        preview_ok = False
        preview_error = "fast_forward would fail — branch diverged"
    else:
        preview_ok = remote_info is not None
        preview_error = "" if preview_ok else "remote branch not found — fetch remotes first"

    payload: dict = {
        "project_id": project_id,
        "git_mode": mode,
        "git_mode_requested": git_mode.strip() or "auto",
        "sync_strategy": preview_strategy,
        "branch": effective_branch,
        "branch_requested": branch.strip(),
        "base_repo": {
            "path": str(base_path),
            "branch": base_status["branch"],
            "commit": base_status["commit"],
            "dirty_count": base_status["dirty_count"],
            "has_conflicts": base_status["has_conflicts"],
        },
        "build_workspace": {
            "path": str(workspace_path),
            "exists": workspace_exists,
            "branch": workspace_status_data["branch"],
            "commit": workspace_status_data["commit"],
            "dirty_count": workspace_status_data["dirty_count"],
            "has_conflicts": workspace_status_data["has_conflicts"],
        },
        "remote": {
            "name": git_cfg["remote"],
            "branch": effective_branch,
            "commit": remote_info["commit"] if remote_info else "unknown",
            "commit_full": remote_info["commit_full"] if remote_info else "",
            "subject": remote_info["subject"] if remote_info else "",
            "fetched_at": fetch_state.get("at", "") if fetch_state else "",
        },
        "sync_status": comparison.get("sync_status", "unknown"),
        "commits_ahead": comparison.get("commits_ahead", 0),
        "commits_behind": comparison.get("commits_behind", 0),
        "last_sync": sync_state or {},
        "sync_preview": {
            "strategy": preview_strategy,
            "would_update": comparison.get("sync_status") in {"behind", "diverged", "unknown"},
            "target_commit": preview_after[:7] if preview_after else "",
            "target_commit_full": preview_after,
            "ok": preview_ok,
            "error": preview_error,
        },
        "require_sync_before_build": git_cfg["require_sync_before_build"],
        "allow_stale_build": git_cfg["allow_stale_build"],
    }

    if ota_dir is not None:
        payload["last_build_commit"] = last_build_commit(ota_dir, project_id) or {}

    return payload


def _ota_builder_root() -> Path:
    return Path(os.environ.get("OTA_BUILDER_ROOT", Path(__file__).resolve().parent.parent))


def git_sync(
    projects_json: Path,
    project_id: str,
    *,
    branch: str = "",
    git_mode: str = "auto",
    strategy: str = "",
) -> dict:
    validate_project_id(project_id)
    git_cfg = get_git_config(projects_json, project_id)
    sync_strategy = strategy.strip() or git_cfg["default_sync_strategy"]
    if sync_strategy not in SYNC_STRATEGIES:
        raise GitApiError("invalid sync_strategy")

    root = _ota_builder_root()
    script = root / "scripts" / "prepare_git_workspace.sh"
    if not script.is_file():
        raise GitApiError(f"sync script not found: {script}")

    env = os.environ.copy()
    env["OTA_BUILDER_ROOT"] = str(root)
    cmd = [
        "bash",
        str(script),
        "--sync-only",
        "--json",
        "--strategy",
        sync_strategy,
        project_id,
        branch.strip(),
        git_mode.strip() or "auto",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=root, env=env, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GitApiError(detail or "git sync failed")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitApiError(f"invalid sync response: {exc}") from exc

    status = workspace_status(
        projects_json,
        project_id,
        branch=branch,
        git_mode=git_mode,
    )
    payload["sync_status"] = status["sync_status"]
    payload["commits_ahead"] = status["commits_ahead"]
    payload["commits_behind"] = status["commits_behind"]
    payload["project_id"] = project_id
    return payload


def sync_preview(
    projects_json: Path,
    project_id: str,
    *,
    branch: str = "",
    git_mode: str = "auto",
    strategy: str = "",
) -> dict:
    status = workspace_status(projects_json, project_id, branch=branch, git_mode=git_mode)
    sync_strategy = strategy.strip() or status["sync_strategy"]
    if sync_strategy not in SYNC_STRATEGIES:
        raise GitApiError("invalid sync_strategy")

    remote_full = status["remote"].get("commit_full", "")
    workspace_full = status["build_workspace"].get("commit", "")
    if status["build_workspace"]["exists"]:
        base_path = get_project_repo_path(projects_json, project_id)
        workspace_path = Path(status["build_workspace"]["path"])
        local = _commit_details(workspace_path, "HEAD")
        workspace_full = local["commit_full"] if local else workspace_full

    would_fail = False
    error = ""
    if not remote_full:
        would_fail = True
        error = "remote branch not found — fetch remotes first"
    elif sync_strategy == "fast_forward" and status["sync_status"] == "diverged":
        would_fail = True
        error = "fast_forward would fail — branch diverged"

    target_full = remote_full
    if sync_strategy == "fast_forward" and status["sync_status"] == "ahead":
        target_full = workspace_full

    return {
        "project_id": project_id,
        "branch": status["branch"],
        "git_mode": status["git_mode"],
        "strategy": sync_strategy,
        "current_commit": workspace_full,
        "target_commit": target_full,
        "target_commit_short": target_full[:7] if target_full else "",
        "sync_status": status["sync_status"],
        "commits_ahead": status["commits_ahead"],
        "commits_behind": status["commits_behind"],
        "would_update": bool(remote_full and workspace_full != remote_full),
        "ok": not would_fail,
        "error": error,
    }


def check_secrets_sync(base_path: Path, secrets_sync: list[str]) -> dict:
    missing: list[str] = []
    present: list[str] = []
    for rel in secrets_sync:
        rel = rel.strip().lstrip("/")
        if not rel or ".." in Path(rel).parts:
            continue
        src = base_path / rel
        if src.is_file() or src.is_dir():
            present.append(rel)
        else:
            missing.append(rel)
    return {"present": present, "missing": missing}
