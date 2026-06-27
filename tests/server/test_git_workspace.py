"""Additional tests for git workspace sync (F31)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from git_api import (
    GitApiError,
    compare_with_remote,
    resolve_build_workspace_path,
    slugify_branch,
    sync_preview,
    workspace_status,
)


def _init_repo(path: Path, *, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-b", branch], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_slugify_branch() -> None:
    assert slugify_branch("Feature/My-Branch") == "feature-my-branch"


def test_compare_with_remote_in_sync(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    result = compare_with_remote(repo, branch="main", remote="origin")
    assert result["sync_status"] in {"in_sync", "unknown"}


def test_workspace_status_unknown_remote_branch(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"path": str(repo)}}}),
        encoding="utf-8",
    )
    status = workspace_status(projects_json, "my-app", branch="feature/x", git_mode="checkout")
    assert status["project_id"] == "my-app"
    assert status["branch"] == "feature/x"
    assert status["sync_status"] == "unknown"


def test_resolve_build_workspace_path_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    wt_base = tmp_path / "worktrees"
    path = resolve_build_workspace_path(
        repo,
        project_id="my-app",
        branch="feature/x",
        git_mode="worktree",
        worktree_base=str(wt_base),
    )
    assert path == wt_base / "feature-x"


def test_sync_preview_unknown_branch(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"path": str(repo)}}}),
        encoding="utf-8",
    )
    preview = sync_preview(projects_json, "my-app", branch="missing", git_mode="checkout")
    assert preview["ok"] is False
    assert preview["error"]


def test_get_git_config_includes_sync_defaults(tmp_path: Path) -> None:
    from git_api import get_git_config

    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"path": "/tmp/app", "git": {"remote": "origin"}}}}),
        encoding="utf-8",
    )
    cfg = get_git_config(projects_json, "my-app")
    assert cfg["default_sync_strategy"] == "match_remote"
    assert cfg["require_sync_before_build"] is True
    assert cfg["allow_stale_build"] is False
