"""Tests for prepare_git_workspace.sh sync behavior."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
PROJECTS_JSON = CONFIG_DIR / "projects.json"
LOCAL_ENV = CONFIG_DIR / "local.env"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "v1"], cwd=path, check=True, capture_output=True)


def _run_prepare(
    *,
    branch: str = "main",
    git_mode: str = "checkout",
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OTA_BUILDER_ROOT"] = str(ROOT)
    cmd = [
        "bash",
        str(ROOT / "scripts" / "prepare_git_workspace.sh"),
        *(extra_args or []),
        "my-app",
        branch,
        git_mode,
    ]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)


@pytest.fixture
def builder_config(tmp_path: Path):
    backups: dict[Path, bytes | None] = {}
    for path in (PROJECTS_JSON, LOCAL_ENV):
        backups[path] = path.read_bytes() if path.is_file() else None

    LOCAL_ENV.write_text(
        "\n".join(
            [
                f"OTA_BASE_URL=https://ota.example.com",
                "OTA_ACCESS_TOKEN=test-token",
                "APPLE_TEAM_ID=TESTTEAM",
                f"OTA_BUILDS_DIR={tmp_path / 'builds'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "builds").mkdir(parents=True, exist_ok=True)

    yield tmp_path

    for path, content in backups.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)


@pytest.fixture
def synced_remote_repo(builder_config: Path) -> tuple[Path, Path]:
    bare = builder_config / "origin.git"
    app = builder_config / "app"
    app.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    _init_repo(app)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=app, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=app, check=True, capture_output=True)

    PROJECTS_JSON.write_text(
        json.dumps(
            {
                "projects": {
                    "my-app": {
                        "display_name": "My App",
                        "path": str(app),
                        "xcodeproj": "App.xcodeproj",
                        "scheme": "App",
                        "configuration": "Release",
                        "bundle_id": "com.example.app",
                        "git": {"remote": "origin"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return app, bare


def test_second_sync_picks_up_new_remote_commit(synced_remote_repo: tuple[Path, Path]) -> None:
    app, bare = synced_remote_repo

    first = _run_prepare(extra_args=["--strategy", "match_remote"])
    assert first.returncode == 0, first.stderr
    first_head = subprocess.check_output(["git", "-C", str(app), "rev-parse", "HEAD"], text=True).strip()

    (app / "README.md").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=app, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "v2"], cwd=app, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=app, check=True, capture_output=True)

    second = _run_prepare(extra_args=["--strategy", "match_remote"])
    assert second.returncode == 0, second.stderr
    second_head = subprocess.check_output(["git", "-C", str(app), "rev-parse", "HEAD"], text=True).strip()
    remote_head = subprocess.check_output(["git", "-C", str(bare), "rev-parse", "main"], text=True).strip()

    assert first_head != second_head
    assert second_head == remote_head


def test_sync_only_json_output(synced_remote_repo: tuple[Path, Path]) -> None:
    result = _run_prepare(
        extra_args=["--sync-only", "--json", "--strategy", "match_remote"],
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["strategy"] == "match_remote"
    assert payload["after"]["commit_full"]
