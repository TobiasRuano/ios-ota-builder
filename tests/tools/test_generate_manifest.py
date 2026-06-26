"""Tests for tools/generate_manifest.py."""

from __future__ import annotations

import plistlib
import re

from generate_manifest import _format_build_date, build_install_html, build_manifest


def test_build_manifest_contains_required_fields() -> None:
    data = build_manifest(
        title="My App",
        bundle_id="com.example.myapp",
        bundle_version="1.2.0",
        ipa_url="https://ota.example.com/my-app/06-26-42/app.ipa?token=secret",
    )
    manifest = plistlib.loads(data)
    item = manifest["items"][0]
    assert item["assets"][0]["url"] == "https://ota.example.com/my-app/06-26-42/app.ipa?token=secret"
    assert item["metadata"]["bundle-identifier"] == "com.example.myapp"
    assert item["metadata"]["bundle-version"] == "1.2.0"
    assert item["metadata"]["title"] == "My App"


def test_format_build_date_iso_utc() -> None:
    assert _format_build_date("2025-06-26T14:30:00Z") == "26 Jun 2025, 14:30 UTC"


def test_format_build_date_invalid_passthrough() -> None:
    assert _format_build_date("not-a-date") == "not-a-date"


def test_build_install_html_encodes_manifest_url() -> None:
    manifest_url = "https://ota.example.com/my-app/06-26-42/manifest.plist?token=abc%2Bdef"
    html = build_install_html(
        title="My App",
        manifest_url=manifest_url,
        ipa_url="https://ota.example.com/my-app/06-26-42/app.ipa",
        install_page_url="https://ota.example.com/my-app/06-26-42/install.html",
        version="1.0.0",
        build_number="42",
        branch="main",
        commit="abc1234",
        build_date="2025-06-26T12:00:00Z",
        configuration="Release",
    )
    match = re.search(r'href="(itms-services://[^"]+)"', html)
    assert match is not None
    install_href = match.group(1)
    assert "itms-services://?action=download-manifest&url=" in install_href
    assert "token" in install_href
    assert "Install App" in html
    assert "1.0.0 (42)" in html


def test_build_install_html_debug_badge() -> None:
    html = build_install_html(
        title="My App",
        manifest_url="https://ota.example.com/manifest.plist",
        ipa_url="https://ota.example.com/app.ipa",
        install_page_url="https://ota.example.com/install.html",
        version="1.0.0",
        build_number="1",
        branch="dev",
        commit="abc",
        build_date="2025-06-26T12:00:00Z",
        configuration="Debug",
    )
    assert "badge-debug" in html
    assert "Debug" in html
