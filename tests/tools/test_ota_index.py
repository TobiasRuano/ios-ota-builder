"""Tests for tools/ota_index.py logic functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import write_failure_build, write_success_build
from ota_index import (
    _build_entry_if_valid,
    _build_failure_entry,
    _build_sort_key,
    _fallback_build_label,
    _find_ipa_file,
    _format_duration,
    _format_ipa_size,
    _is_compact_build_dir,
    _parse_build_number,
    _resolve_configuration,
    collect_builds,
    collect_disk_stats,
    find_latest_build,
    format_uptime,
    load_projects_config,
    load_summary,
)


def test_load_summary_returns_none_when_missing(ota_dir: Path) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    assert load_summary(build_dir) is None


def test_load_summary_returns_none_for_invalid_json(ota_dir: Path) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    (build_dir / "summary.json").write_text("{not json", encoding="utf-8")
    assert load_summary(build_dir) is None


def test_is_compact_build_dir() -> None:
    assert _is_compact_build_dir("06-26-42") is True
    assert _is_compact_build_dir("06-26-debug") is False
    assert _is_compact_build_dir("legacy-name") is False


def test_parse_build_number_from_summary() -> None:
    entry = {"build_number": "99"}
    assert _parse_build_number(entry, Path("06-26-42")) == 99


def test_parse_build_number_from_compact_dir_name() -> None:
    entry: dict = {}
    assert _parse_build_number(entry, Path("06-26-142")) == 142


def test_build_sort_key_prefers_date_over_mtime(ota_dir: Path) -> None:
    build_dir = write_success_build(
        ota_dir,
        "my-app",
        "06-26-10",
        date="2025-06-26T18:00:00Z",
        build_number="10",
    )
    entry = _build_entry_if_valid(build_dir, "my-app")
    assert entry is not None
    key = _build_sort_key(entry, build_dir)
    assert key[1] == 10
    assert key[0] > 0


def test_resolve_configuration() -> None:
    assert _resolve_configuration("06-26-42", {"configuration": "Debug"}) == "Debug"
    assert _resolve_configuration("06-26-debug", None) == "Debug"
    assert _resolve_configuration("06-26-42", None) == "Release"


def test_format_duration() -> None:
    assert _format_duration(None) == "—"
    assert _format_duration(45) == "45s"
    assert _format_duration(125) == "2m 5s"
    assert _format_duration(3665) == "1h 1m"


def test_format_ipa_size() -> None:
    assert _format_ipa_size(None) == "—"
    assert _format_ipa_size(5_000_000) == "4.77 MB"
    assert _format_ipa_size(50_000_000) == "47.7 MB"
    assert _format_ipa_size(150_000_000) == "143 MB"


def test_find_ipa_file_prefers_app_ipa(ota_dir: Path) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    (build_dir / "app.ipa").write_bytes(b"x")
    (build_dir / "other.ipa").write_bytes(b"y")
    assert _find_ipa_file(build_dir).name == "app.ipa"


def test_find_ipa_file_single_glob(ota_dir: Path) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    (build_dir / "MyApp.ipa").write_bytes(b"x")
    assert _find_ipa_file(build_dir).name == "MyApp.ipa"


def test_fallback_build_label() -> None:
    entry = {"build_label": "Beta 3"}
    assert _fallback_build_label(entry, Path("06-26-42")) == "Beta 3"
    assert _fallback_build_label({"build_number": "7"}, Path("06-26-7")) == "#7"


def test_build_entry_if_valid_success(ota_dir: Path) -> None:
    build_dir = write_success_build(ota_dir, "my-app", "06-26-42")
    entry = _build_entry_if_valid(build_dir, "my-app")
    assert entry is not None
    assert entry["status"] == "success"
    assert entry["has_ipa"] is True
    assert entry["has_install"] is True
    assert entry["configuration"] == "Release"


def test_build_failure_entry(ota_dir: Path) -> None:
    build_dir = write_failure_build(ota_dir, "my-app", "06-25-fail")
    summary = load_summary(build_dir)
    assert summary is not None
    entry = _build_failure_entry(build_dir, "my-app", summary)
    assert entry["status"] == "failure"
    assert entry["has_ipa"] is False
    assert entry["has_diagnostics"] is True
    assert entry["has_log"] is True


def test_find_latest_build_picks_newest_success(ota_dir: Path, projects_config: dict) -> None:
    write_success_build(
        ota_dir,
        "my-app",
        "06-26-10",
        date="2025-06-26T10:00:00Z",
        build_number="10",
    )
    write_success_build(
        ota_dir,
        "my-app",
        "06-26-42",
        date="2025-06-26T18:00:00Z",
        build_number="42",
    )
    write_failure_build(ota_dir, "my-app", "06-26-fail")

    latest = find_latest_build(ota_dir, "my-app", projects_config=projects_config)
    assert latest is not None
    assert latest["build_dir"] == "06-26-42"


def test_find_latest_build_unknown_project(ota_dir: Path, projects_config: dict) -> None:
    assert find_latest_build(ota_dir, "unknown", projects_config=projects_config) is None


def test_collect_builds_marks_latest_success(ota_dir: Path, projects_config: dict) -> None:
    write_success_build(ota_dir, "my-app", "06-26-10", build_number="10")
    write_success_build(ota_dir, "my-app", "06-26-42", build_number="42")
    write_failure_build(ota_dir, "my-app", "06-26-fail")

    data = collect_builds(ota_dir, projects_config)
    builds = data["projects"]["my-app"]["builds"]
    latest_flags = [b.get("is_latest") for b in builds if b.get("is_latest")]
    assert len(latest_flags) == 1
    latest_build = next(b for b in builds if b.get("is_latest"))
    assert latest_build["build_number"] == "42"


def test_collect_disk_stats(ota_dir: Path) -> None:
    stats = collect_disk_stats(ota_dir, min_disk_mb=1)
    assert "free_mb" in stats
    assert "ok" in stats
    assert stats.get("unavailable") is not True


def test_format_uptime() -> None:
    assert format_uptime(0) == "0m"
    assert format_uptime(90) == "1m"
    assert format_uptime(3661) == "1h 1m"
    assert format_uptime(90061) == "1d 1h 1m"


def test_load_projects_config(tmp_path: Path) -> None:
    config_path = tmp_path / "projects.json"
    config_path.write_text(
        json.dumps({"projects": {"my-app": {"display_name": "My App"}}}),
        encoding="utf-8",
    )
    assert load_projects_config(config_path) == {"my-app": {"display_name": "My App"}}


def test_load_projects_config_missing_file(tmp_path: Path) -> None:
    assert load_projects_config(tmp_path / "missing.json") == {}
