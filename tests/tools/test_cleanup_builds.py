"""Tests for tools/cleanup_builds.py."""

from __future__ import annotations

import os
import time
from pathlib import Path

from cleanup_builds import cleanup_project, purge_build_work


def _touch_dir(path: Path, mtime: float) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.utime(path, (mtime, mtime))


def test_cleanup_project_respects_keep_count(ota_dir: Path) -> None:
    project_dir = ota_dir / "my-app"
    now = time.time()
    builds = []
    for idx, name in enumerate(["old", "mid", "new"]):
        build = project_dir / name
        _touch_dir(build, now - (3 - idx) * 3600)
        builds.append(build)

    removed = cleanup_project(project_dir, keep=2, max_age_days=365)

    assert len(removed) == 1
    assert removed[0].name == "old"
    assert (project_dir / "mid").exists()
    assert (project_dir / "new").exists()


def test_cleanup_project_removes_too_old(ota_dir: Path) -> None:
    project_dir = ota_dir / "my-app"
    now = time.time()
    recent = project_dir / "recent"
    ancient = project_dir / "ancient"
    _touch_dir(recent, now - 3600)
    _touch_dir(ancient, now - 30 * 86400)

    removed = cleanup_project(project_dir, keep=10, max_age_days=7)

    assert ancient in removed
    assert recent.exists()


def test_cleanup_project_empty_dir(ota_dir: Path) -> None:
    project_dir = ota_dir / "my-app"
    project_dir.mkdir(parents=True)
    assert cleanup_project(project_dir, keep=5, max_age_days=7) == []


def test_purge_build_work_removes_work_dir(ota_dir: Path) -> None:
    build = ota_dir / "my-app" / "kept"
    work = build / "work" / "DerivedData"
    work.mkdir(parents=True)
    (build / "app.ipa").write_text("ipa", encoding="utf-8")

    assert purge_build_work(build) is True
    assert not (build / "work").exists()
    assert (build / "app.ipa").exists()
    assert purge_build_work(build) is False


def test_cleanup_project_strips_work_from_retained(ota_dir: Path) -> None:
    project_dir = ota_dir / "my-app"
    now = time.time()
    kept = project_dir / "kept"
    old = project_dir / "old"
    _touch_dir(kept, now - 3600)
    _touch_dir(old, now - 7200)
    (kept / "work" / "DerivedData").mkdir(parents=True)
    (old / "work" / "DerivedData").mkdir(parents=True)
    (kept / "app.ipa").write_text("ipa", encoding="utf-8")

    removed = cleanup_project(project_dir, keep=1, max_age_days=365)

    assert removed == [old]
    assert kept.exists()
    assert not (kept / "work").exists()
    assert (kept / "app.ipa").exists()
    assert not old.exists()
