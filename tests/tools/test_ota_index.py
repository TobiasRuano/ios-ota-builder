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
    _format_dashboard_timestamp,
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
    render_index,
    render_status_panel,
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


def test_format_dashboard_timestamp() -> None:
    assert _format_dashboard_timestamp("2025-06-26T12:00:00Z") == "26 Jun 2025, 12:00 UTC"
    assert _format_dashboard_timestamp("") == "—"
    assert _format_dashboard_timestamp("not-a-date") == "not-a-date"


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


def test_render_status_panel_includes_restart_button_when_action_provided() -> None:
    status = {"disk": {"free_gb": 42.1, "ok": True}, "uptime_seconds": 3600}
    html = render_status_panel(status, restart_action="/?token=secret")
    assert "btn-restart-server" in html
    assert 'data-restart-action="/?token=secret"' in html
    assert "Restart server" in html


def test_render_status_panel_omits_restart_button_without_action() -> None:
    status = {"disk": {"free_gb": 42.1, "ok": True}, "uptime_seconds": 3600}
    html = render_status_panel(status)
    assert "btn-restart-server" not in html


def test_render_index_includes_restart_controls_when_token_present() -> None:
    data = {"generated_at": "2025-06-26T12:00:00Z", "projects": {}}
    status = {"disk": {"free_gb": 42.1, "ok": True}, "uptime_seconds": 3600}
    html = render_index(
        data,
        "https://ota.example.com",
        "secret",
        server_status=status,
    )
    assert "btn-restart-server" in html
    assert "/api/server/restart?token=secret" in html
    assert "pollHealth" in html


def test_render_index_omits_restart_controls_without_token() -> None:
    data = {"generated_at": "2025-06-26T12:00:00Z", "projects": {}}
    status = {"disk": {"free_gb": 42.1, "ok": True}, "uptime_seconds": 3600}
    html = render_index(
        data,
        "https://ota.example.com",
        None,
        enable_restart=False,
        server_status=status,
    )
    assert '<button type="button" class="btn-restart-server"' not in html
    assert 'data-restart-action="/api/server/restart' not in html


def test_render_index_includes_logout_when_enabled() -> None:
    data = {"generated_at": "2025-06-26T12:00:00Z", "projects": {}}
    html = render_index(data, "https://ota.example.com", "secret", enable_logout=True)
    assert 'action="/api/logout"' in html
    assert "Sign out" in html
    assert 'class="page-header-actions"' in html
    assert 'class="btn-secondary"' in html
    assert 'class="btn-primary">Sign out' not in html


def test_render_index_formats_last_updated_timestamp() -> None:
    data = {"generated_at": "2025-06-26T12:00:00Z", "projects": {}}
    html = render_index(data, "https://ota.example.com", None)
    assert "Last updated 26 Jun 2025, 12:00 UTC" in html
    assert "Generated 2025-06-26T12:00:00Z" not in html
    assert 'class="muted page-header-meta"' in html


def test_render_index_includes_colgroup(ota_dir: Path, projects_config: dict) -> None:
    write_success_build(ota_dir, "my-app", "06-26-42")
    data = collect_builds(ota_dir, projects_config)
    html = render_index(data, "https://ota.example.com", None)
    assert '<col class="col-build">' in html
    assert '<col class="col-branch">' in html
    assert '<col class="col-actions">' in html
    assert 'class="cell-actions"' in html


def test_render_index_truncates_long_branch_with_title(
    ota_dir: Path, projects_config: dict
) -> None:
    build_dir = write_success_build(ota_dir, "my-app", "06-26-42")
    summary = json.loads((build_dir / "summary.json").read_text(encoding="utf-8"))
    long_branch = "feature/pf-159-ui-derived-snapshots"
    summary["branch"] = long_branch
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    data = collect_builds(ota_dir, projects_config)
    html = render_index(data, "https://ota.example.com", None)
    assert 'class="cell-truncate"' in html
    assert f'title="{long_branch}"' in html
    assert long_branch in html


def test_render_index_omits_logout_by_default() -> None:
    data = {"generated_at": "2025-06-26T12:00:00Z", "projects": {}}
    html = render_index(data, "https://ota.example.com", "secret")
    assert 'action="/api/logout"' not in html


def test_render_build_panel_includes_controls() -> None:
    from ota_index import render_build_panel

    html = render_build_panel(
        "my-app",
        trigger_url="/api/builds/trigger?token=secret",
        git_status_url="/api/git/status?token=secret&project=my-app",
        git_branches_url="/api/git/branches?token=secret&project=my-app",
        git_fetch_url="/api/git/fetch?token=secret",
        jobs_url="/api/builds/jobs?token=secret",
    )
    assert "build-panel" in html
    assert 'id="build-panel-my-app"' in html
    assert " hidden" in html
    assert "Start build" in html
    assert "btn-build-cancel" in html
    assert 'data-project-id="my-app"' in html
    assert "build-panel-title" not in html


def test_render_build_toggle_button() -> None:
    from ota_index import render_build_toggle_button

    html = render_build_toggle_button("my-app")
    assert 'class="btn-new-build-toggle"' in html
    assert 'aria-controls="build-panel-my-app"' in html
    assert 'aria-expanded="false"' in html
    assert "New build" in html


def test_render_index_includes_build_panel_when_token_present() -> None:
    data = {
        "generated_at": "2025-06-26T12:00:00Z",
        "projects": {"my-app": {"display_name": "My App", "builds": []}},
    }
    html = render_index(data, "https://ota.example.com", "secret")
    assert "build-panel" in html
    assert 'class="build-panel" id="build-panel-my-app" hidden' in html
    assert "btn-new-build-toggle" in html
    assert "btn-build-start" in html
    assert "/api/builds/trigger?token=secret" in html
    assert "window.__OTA_TOKEN" in html


def test_render_index_omits_build_panel_without_token() -> None:
    data = {"generated_at": "2025-06-26T12:00:00Z", "projects": {}}
    html = render_index(data, "https://ota.example.com", None, enable_build=False)
    assert 'class="build-panel"' not in html
    assert 'class="btn-build-start"' not in html


def test_collect_builds_includes_release_notes(ota_dir: Path, projects_config: dict) -> None:
    build_dir = write_success_build(ota_dir, "my-app", "06-26-42")
    summary = json.loads((build_dir / "summary.json").read_text(encoding="utf-8"))
    summary["release_notes"] = "Fixed login crash"
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    data = collect_builds(ota_dir, projects_config)
    builds = data["projects"]["my-app"]["builds"]
    assert builds[0]["release_notes"] == "Fixed login crash"


def test_render_index_includes_build_notes_details(ota_dir: Path, projects_config: dict) -> None:
    build_dir = write_success_build(ota_dir, "my-app", "06-26-42")
    summary = json.loads((build_dir / "summary.json").read_text(encoding="utf-8"))
    summary["release_notes"] = "Fixed login crash"
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    data = collect_builds(ota_dir, projects_config)
    html = render_index(data, "https://ota.example.com", None)
    assert 'class="build-notes"' in html
    assert "Fixed login crash" in html
    assert "Release notes" in html
