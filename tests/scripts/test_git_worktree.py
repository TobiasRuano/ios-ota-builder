"""Tests for scripts/lib/common.sh — check_git_worktree (F13)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _init_git_repo(path: Path, *, commit: bool = True) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    if commit:
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def _run_check_git_worktree(
    repo_path: Path,
    *,
    ota_fail_on_dirty: str | None = None,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["OTA_BUILDER_ROOT"] = str(ROOT)
    if ota_fail_on_dirty is not None:
        env["OTA_FAIL_ON_DIRTY"] = ota_fail_on_dirty
    else:
        env.pop("OTA_FAIL_ON_DIRTY", None)

    script = f"""
    set -euo pipefail
    source "{ROOT}/scripts/lib/common.sh"
    set +e
    check_git_worktree "{repo_path}"
    ec=$?
    printf 'EXIT:%s\\n' "$ec"
    printf 'COUNT:%s\\n' "${{GIT_DIRTY_COUNT:-}}"
    """
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    exit_line = next((line for line in combined.splitlines() if line.startswith("EXIT:")), "EXIT:?")
    count_line = next((line for line in combined.splitlines() if line.startswith("COUNT:")), "COUNT:?")
    ec = int(exit_line.split(":", 1)[1])
    count = count_line.split(":", 1)[1]
    return ec, count, combined


@pytest.fixture
def clean_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


def test_check_git_worktree_clean_repo(clean_git_repo: Path) -> None:
    ec, count, output = _run_check_git_worktree(clean_git_repo)
    assert ec == 0
    assert count == "0"
    assert "WARN:" not in output


def test_check_git_worktree_dirty_untracked(clean_git_repo: Path) -> None:
    (clean_git_repo / "new.txt").write_text("dirty\n", encoding="utf-8")
    ec, count, output = _run_check_git_worktree(clean_git_repo)
    assert ec == 0
    assert count == "1"
    assert "WARN:" in output
    assert "1 uncommitted change(s)" in output


def test_check_git_worktree_dirty_modified(clean_git_repo: Path) -> None:
    (clean_git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
    ec, count, output = _run_check_git_worktree(clean_git_repo)
    assert ec == 0
    assert count == "1"
    assert "WARN:" in output


def test_check_git_worktree_fail_on_dirty(clean_git_repo: Path) -> None:
    (clean_git_repo / "new.txt").write_text("dirty\n", encoding="utf-8")
    ec, count, output = _run_check_git_worktree(clean_git_repo, ota_fail_on_dirty="1")
    assert ec == 1
    assert count == "1"
    assert "OTA_FAIL_ON_DIRTY=1" in output


def test_check_git_worktree_non_git_path(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    ec, count, output = _run_check_git_worktree(plain)
    assert ec == 0
    assert count == "0"
    assert "WARN:" not in output


def test_agent_build_ota_wires_check_git_worktree() -> None:
    content = (ROOT / "agent_build_ota.sh").read_text(encoding="utf-8")
    assert 'git_metadata "$PROJECT_PATH"' in content
    assert 'check_git_worktree "$PROJECT_PATH"' in content
    git_idx = content.index('git_metadata "$PROJECT_PATH"')
    check_idx = content.index('check_git_worktree "$PROJECT_PATH"')
    assert check_idx > git_idx
