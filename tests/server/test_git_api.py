"""Tests for server/git_api.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from git_api import (
    GitApiError,
    check_secrets_sync,
    get_project_repo_path,
    git_status,
    list_branches,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_git_status_clean_repo(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    status = git_status(repo)
    assert status["is_git_repo"] is True
    assert status["branch"] == "main"
    assert status["dirty_count"] == 0


def test_git_status_dirty_repo(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    (repo / "new.txt").write_text("x", encoding="utf-8")
    status = git_status(repo)
    assert status["dirty_count"] == 1


def test_list_branches(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    branches = list_branches(repo)
    assert "main" in branches["local"]
    assert branches["current"] == "main"


def test_get_project_repo_path(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo)
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"path": str(repo)}}}),
        encoding="utf-8",
    )
    assert get_project_repo_path(projects_json, "my-app") == repo.resolve()


def test_get_project_repo_path_unknown(tmp_path: Path) -> None:
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    with pytest.raises(GitApiError, match="unknown project_id"):
        get_project_repo_path(projects_json, "missing")


def test_check_secrets_sync(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    secrets_dir = repo / "Config"
    secrets_dir.mkdir()
    (secrets_dir / "Secrets.xcconfig").write_text("KEY=1", encoding="utf-8")
    result = check_secrets_sync(repo, ["Config/Secrets.xcconfig", "Missing.plist"])
    assert "Config/Secrets.xcconfig" in result["present"]
    assert "Missing.plist" in result["missing"]
