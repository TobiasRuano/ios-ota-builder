"""Git introspection and operations for dashboard build triggers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from build_jobs import BuildJobError, PROJECT_ID_RE


class GitApiError(ValueError):
    pass


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
    return {"ok": True, "remote": remote}


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
