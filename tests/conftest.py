"""Shared pytest fixtures for ios-ota-builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def ota_dir(tmp_path: Path) -> Path:
    """Empty OTA builds root directory."""
    root = tmp_path / "OTA-Builds"
    root.mkdir()
    return root


def write_success_build(
    ota_dir: Path,
    project_id: str,
    build_dir_name: str,
    *,
    build_number: str = "42",
    date: str = "2025-06-26T12:00:00Z",
    configuration: str = "Release",
    version: str = "1.0.0",
) -> Path:
    """Create a minimal successful build directory on disk."""
    build_dir = ota_dir / project_id / build_dir_name
    build_dir.mkdir(parents=True)
    (build_dir / "app.ipa").write_bytes(b"fake-ipa")
    (build_dir / "install.html").write_text("<html></html>", encoding="utf-8")
    summary = {
        "status": "success",
        "branch": "main",
        "commit": "abc1234",
        "date": date,
        "version": version,
        "build_number": build_number,
        "configuration": configuration,
        "install_url": f"https://ota.example.com/{project_id}/{build_dir_name}/install.html",
        "manifest_url": f"https://ota.example.com/{project_id}/{build_dir_name}/manifest.plist",
        "ipa_url": f"https://ota.example.com/{project_id}/{build_dir_name}/app.ipa",
        "duration_seconds": 120,
        "ipa_size_bytes": 5_000_000,
    }
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return build_dir


def write_failure_build(
    ota_dir: Path,
    project_id: str,
    build_dir_name: str,
    *,
    stage: str = "archive",
) -> Path:
    """Create a minimal failed build directory on disk."""
    build_dir = ota_dir / project_id / build_dir_name
    build_dir.mkdir(parents=True)
    summary = {
        "status": "failure",
        "stage": stage,
        "branch": "main",
        "commit": "def5678",
        "date": "2025-06-25T10:00:00Z",
        "version": "1.0.0",
        "build_number": "41",
    }
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (build_dir / "diagnostics.md").write_text("# Build Diagnostics\n", encoding="utf-8")
    (build_dir / "archive.log").write_text("error: ARCHIVE FAILED\n", encoding="utf-8")
    return build_dir


@pytest.fixture
def projects_config() -> dict:
    return {
        "my-app": {"display_name": "My App"},
        "other-app": {"display_name": "Other App"},
    }
