"""Tests for commit URL helpers (F10)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import write_success_build
from ota_index import (
    _format_commit_cell,
    collect_builds,
    commit_url,
    render_index,
)

FULL_SHA = "abc1234567890abcdef1234567890abcdef12345678"
SHORT_SHA = "abc1234"


def test_commit_url_github() -> None:
    url = commit_url("https://github.com/user/repo", "github", FULL_SHA)
    assert url == f"https://github.com/user/repo/commit/{FULL_SHA}"


def test_commit_url_gitlab() -> None:
    url = commit_url("https://gitlab.com/user/repo", "gitlab", FULL_SHA)
    assert url == f"https://gitlab.com/user/repo/-/commit/{FULL_SHA}"


def test_commit_url_strips_trailing_slash() -> None:
    url = commit_url("https://github.com/user/repo/", "github", SHORT_SHA)
    assert url == f"https://github.com/user/repo/commit/{SHORT_SHA}"


def test_commit_url_defaults_to_github() -> None:
    url = commit_url("https://github.com/user/repo", None, SHORT_SHA)
    assert url == f"https://github.com/user/repo/commit/{SHORT_SHA}"


def test_commit_url_returns_none_without_repo_url() -> None:
    assert commit_url(None, "github", SHORT_SHA) is None
    assert commit_url("", "github", SHORT_SHA) is None


def test_commit_url_returns_none_for_unknown_sha() -> None:
    assert commit_url("https://github.com/user/repo", "github", "unknown") is None
    assert commit_url("https://github.com/user/repo", "github", None) is None


def test_format_commit_cell_with_github_link() -> None:
    build = {"commit": SHORT_SHA, "commit_full": FULL_SHA}
    project = {
        "repo_url": "https://github.com/user/repo",
        "repo_type": "github",
    }
    cell = _format_commit_cell(build, project)
    assert f'href="https://github.com/user/repo/commit/{FULL_SHA}"' in cell
    assert f">{SHORT_SHA}</a>" in cell
    assert 'target="_blank"' in cell


def test_format_commit_cell_gitlab_path() -> None:
    build = {"commit": SHORT_SHA, "commit_full": FULL_SHA}
    project = {
        "repo_url": "https://gitlab.com/user/repo",
        "repo_type": "gitlab",
    }
    cell = _format_commit_cell(build, project)
    assert f"/-/commit/{FULL_SHA}" in cell


def test_format_commit_cell_plain_text_without_repo_url() -> None:
    build = {"commit": SHORT_SHA, "commit_full": FULL_SHA}
    project = {}
    cell = _format_commit_cell(build, project)
    assert cell == SHORT_SHA
    assert "<a" not in cell


def test_format_commit_cell_unknown_commit() -> None:
    build = {"commit": "unknown"}
    project = {"repo_url": "https://github.com/user/repo"}
    assert _format_commit_cell(build, project) == "—"


def test_format_commit_cell_uses_short_sha_when_commit_full_missing() -> None:
    build = {"commit": SHORT_SHA}
    project = {
        "repo_url": "https://github.com/user/repo",
        "repo_type": "github",
    }
    cell = _format_commit_cell(build, project)
    assert f"/commit/{SHORT_SHA}" in cell


def test_collect_builds_propagates_repo_metadata(ota_dir: Path) -> None:
    write_success_build(ota_dir, "my-app", "06-26-42")
    projects = {
        "my-app": {
            "display_name": "My App",
            "repo_url": "https://github.com/user/repo",
            "repo_type": "gitlab",
        }
    }
    data = collect_builds(ota_dir, projects)
    project = data["projects"]["my-app"]
    assert project["repo_url"] == "https://github.com/user/repo"
    assert project["repo_type"] == "gitlab"


def test_render_index_commit_links(ota_dir: Path) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    (build_dir / "app.ipa").write_bytes(b"fake-ipa")
    (build_dir / "install.html").write_text("<html></html>", encoding="utf-8")
    summary = {
        "status": "success",
        "branch": "main",
        "commit": SHORT_SHA,
        "commit_full": FULL_SHA,
        "date": "2025-06-26T12:00:00Z",
        "version": "1.0.0",
        "build_number": "42",
        "configuration": "Release",
        "install_url": "https://ota.example.com/my-app/06-26-42/install.html",
        "manifest_url": "https://ota.example.com/my-app/06-26-42/manifest.plist",
        "ipa_url": "https://ota.example.com/my-app/06-26-42/app.ipa",
        "duration_seconds": 120,
        "ipa_size_bytes": 5_000_000,
    }
    (build_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    projects = {
        "my-app": {
            "display_name": "My App",
            "repo_url": "https://github.com/user/repo",
            "repo_type": "github",
        }
    }
    data = collect_builds(ota_dir, projects)
    html = render_index(data, "https://ota.example.com", "secret", enable_delete=False)
    assert f"/commit/{FULL_SHA}" in html
    assert f">{SHORT_SHA}</a>" in html
