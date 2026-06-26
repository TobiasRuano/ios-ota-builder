"""Tests for server/ota_dynamic.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ota_dynamic import parse_ota_artifact_path, render_ota_artifact


def test_parse_ota_artifact_path() -> None:
    assert parse_ota_artifact_path("/my-app/06-26-42/install.html") == (
        "my-app",
        "06-26-42",
        "install.html",
    )
    assert parse_ota_artifact_path("/my-app/06-26-42/manifest.plist") == (
        "my-app",
        "06-26-42",
        "manifest.plist",
    )
    assert parse_ota_artifact_path("/my-app/06-26-42/app.ipa") is None


def test_render_ota_artifact_uses_current_token(
    ota_dir: Path,
    tmp_path: Path,
) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    (build_dir / "app.ipa").write_bytes(b"ipa")
    (build_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "display_name": "My App",
                "version": "2.0",
                "build_number": "9",
                "branch": "main",
                "commit": "abc",
                "date": "2026-06-26T12:00:00Z",
                "configuration": "Release",
            }
        ),
        encoding="utf-8",
    )
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps(
            {
                "projects": {
                    "my-app": {
                        "display_name": "My App",
                        "bundle_id": "com.example.myapp",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    rendered = render_ota_artifact(
        ota_dir=ota_dir,
        projects_json=projects_json,
        base_url="https://ota.example.com",
        token="fresh-token",
        project_id="my-app",
        build_dir_name="06-26-42",
        artifact="manifest.plist",
    )
    assert rendered is not None
    body, content_type = rendered
    assert content_type == "application/xml"
    assert b"fresh-token" in body
    assert b"com.example.myapp" in body
