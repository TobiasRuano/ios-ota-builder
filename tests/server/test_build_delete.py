"""Tests for server/build_delete.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from build_delete import BuildDeleteError, delete_build


def test_delete_build_removes_directory(ota_dir: Path) -> None:
    build = ota_dir / "my-app" / "06-26-42"
    build.mkdir(parents=True)
    (build / "app.ipa").write_bytes(b"x")

    removed = delete_build(ota_dir, "my-app", "06-26-42")

    assert removed == build.resolve()
    assert not build.exists()


def test_delete_build_rejects_invalid_project_id(ota_dir: Path) -> None:
    with pytest.raises(BuildDeleteError, match="invalid project_id"):
        delete_build(ota_dir, "../evil", "06-26-42")


def test_delete_build_rejects_invalid_build_dir(ota_dir: Path) -> None:
    with pytest.raises(BuildDeleteError, match="invalid build_dir"):
        delete_build(ota_dir, "my-app", "../escape")


def test_delete_build_rejects_unknown_project(ota_dir: Path) -> None:
    with pytest.raises(BuildDeleteError, match="unknown project_id"):
        delete_build(
            ota_dir,
            "my-app",
            "06-26-42",
            allowed_projects={"other-app"},
        )


def test_delete_build_rejects_missing_directory(ota_dir: Path) -> None:
    with pytest.raises(BuildDeleteError, match="build not found"):
        delete_build(ota_dir, "my-app", "06-26-42")


def test_delete_build_rejects_path_traversal_via_symlink(ota_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep", encoding="utf-8")

    project_dir = ota_dir / "my-app"
    project_dir.mkdir(parents=True)
    link = project_dir / "evil-link"
    link.symlink_to(outside)

    with pytest.raises(BuildDeleteError, match="invalid build path"):
        delete_build(ota_dir, "my-app", "evil-link")

    assert outside.exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep"
