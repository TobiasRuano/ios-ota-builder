"""Tests for scripts/lib/common.sh — release notes helpers (F05)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _init_git_repo(path: Path) -> None:
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


def _git_commit(path: Path, filename: str, message: str) -> str:
    (path / filename).write_text(f"{filename}\n", encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_success_summary(
    ota_dir: Path,
    project_id: str,
    build_dir_name: str,
    *,
    commit: str,
    date: str,
) -> None:
    build_dir = ota_dir / project_id / build_dir_name
    build_dir.mkdir(parents=True)
    summary = {
        "status": "success",
        "commit": commit,
        "date": date,
        "version": "1.0.0",
        "build_number": "1",
    }
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _run_bash(body: str, *, ota_dir: Path, repo_path: Path | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    env["OTA_BUILDER_ROOT"] = str(ROOT)
    env["OTA_BUILDS_DIR"] = str(ota_dir)
    if repo_path is not None:
        env["TEST_REPO_PATH"] = str(repo_path)

    script = f"""
    set -euo pipefail
    source "{ROOT}/scripts/lib/common.sh"
    {body}
    """
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def test_find_previous_successful_commit_picks_newest(tmp_path: Path) -> None:
    ota_dir = tmp_path / "OTA-Builds"
    ota_dir.mkdir()
    _write_success_summary(
        ota_dir,
        "my-app",
        "06-26-10",
        commit="aaa1111",
        date="2025-06-26T10:00:00Z",
    )
    _write_success_summary(
        ota_dir,
        "my-app",
        "06-26-42",
        commit="bbb2222",
        date="2025-06-26T18:00:00Z",
    )

    ec, output = _run_bash(
        """
        commit="$(find_previous_successful_commit my-app 06-26-99)"
        printf 'COMMIT:%s' "$commit"
        """,
        ota_dir=ota_dir,
    )
    assert ec == 0
    assert "COMMIT:bbb2222" in output


def test_find_previous_successful_commit_excludes_current_dir(tmp_path: Path) -> None:
    ota_dir = tmp_path / "OTA-Builds"
    ota_dir.mkdir()
    _write_success_summary(
        ota_dir,
        "my-app",
        "06-26-10",
        commit="aaa1111",
        date="2025-06-26T10:00:00Z",
    )
    _write_success_summary(
        ota_dir,
        "my-app",
        "06-26-42",
        commit="bbb2222",
        date="2025-06-26T18:00:00Z",
    )

    ec, output = _run_bash(
        """
        commit="$(find_previous_successful_commit my-app 06-26-42)"
        printf 'COMMIT:%s' "$commit"
        """,
        ota_dir=ota_dir,
    )
    assert ec == 0
    assert "COMMIT:aaa1111" in output


def test_collect_release_notes_initial_build(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_git_repo(repo)
    _git_commit(repo, "README.md", "init")

    ota_dir = tmp_path / "OTA-Builds"
    ota_dir.mkdir()

    ec, output = _run_bash(
        """
        notes="$(collect_release_notes "$TEST_REPO_PATH" my-app 06-26-42)"
        printf 'NOTES:%s' "$notes"
        """,
        ota_dir=ota_dir,
        repo_path=repo,
    )
    assert ec == 0
    assert "NOTES:Initial build" in output


def test_collect_release_notes_since_previous_commit(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_git_repo(repo)
    first = _git_commit(repo, "a.txt", "first commit")
    _git_commit(repo, "b.txt", "second commit")
    third = _git_commit(repo, "c.txt", "third commit")

    ota_dir = tmp_path / "OTA-Builds"
    ota_dir.mkdir()
    _write_success_summary(
        ota_dir,
        "my-app",
        "06-26-10",
        commit=first,
        date="2025-06-26T10:00:00Z",
    )

    ec, output = _run_bash(
        """
        notes="$(collect_release_notes "$TEST_REPO_PATH" my-app 06-26-42)"
        printf '%s' "$notes"
        """,
        ota_dir=ota_dir,
        repo_path=repo,
    )
    assert ec == 0
    assert "second commit" in output
    assert third in output
    assert "first commit" not in output


def test_collect_release_notes_fallback_for_invalid_previous_commit(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_git_repo(repo)
    _git_commit(repo, "a.txt", "only commit")

    ota_dir = tmp_path / "OTA-Builds"
    ota_dir.mkdir()
    _write_success_summary(
        ota_dir,
        "my-app",
        "06-26-10",
        commit="deadbeef",
        date="2025-06-26T10:00:00Z",
    )

    ec, output = _run_bash(
        """
        notes="$(collect_release_notes "$TEST_REPO_PATH" my-app 06-26-42)"
        printf '%s' "$notes"
        """,
        ota_dir=ota_dir,
        repo_path=repo,
    )
    assert ec == 0
    assert "only commit" in output
