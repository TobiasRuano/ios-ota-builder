#!/usr/bin/env python3
"""Generate OTA manifest.plist and install.html for an iOS build."""

from __future__ import annotations

import argparse
import html
import plistlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_urls import with_access_token
from qr_svg import qr_svg
from ui_theme import base_head


def build_manifest(
    *,
    title: str,
    bundle_id: str,
    bundle_version: str,
    ipa_url: str,
) -> bytes:
    manifest = {
        "items": [
            {
                "assets": [
                    {
                        "kind": "software-package",
                        "url": ipa_url,
                    }
                ],
                "metadata": {
                    "bundle-identifier": bundle_id,
                    "bundle-version": bundle_version,
                    "kind": "software",
                    "title": title,
                },
            }
        ]
    }
    return plistlib.dumps(manifest, fmt=plistlib.FMT_XML)


def _format_build_date(iso: str) -> str:
    """Format ISO UTC timestamp for display on the install page."""
    try:
        normalized = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except (ValueError, TypeError):
        return iso


def _configuration_badge(configuration: str) -> str:
    if configuration == "Debug":
        return (
            '<div class="badge-group">'
            '<span class="status-badge badge-debug">Debug</span>'
            "</div>"
        )
    if configuration == "Release":
        return (
            '<div class="badge-group">'
            '<span class="status-badge badge-release">Release</span>'
            "</div>"
        )
    return ""


def _meta_row(label: str, value: str) -> str:
    return (
        f"<div><dt>{html.escape(label)}</dt>"
        f'<dd>{html.escape(value)}</dd></div>'
    )


def _release_notes_block(release_notes: str) -> str:
    if not release_notes.strip():
        return ""
    safe_notes = html.escape(release_notes.strip())
    return f"""      <div class="install-notes">
        <h2>What&apos;s new</h2>
        <pre class="install-notes-body">{safe_notes}</pre>
      </div>
"""


def build_install_html(
    *,
    title: str,
    manifest_url: str,
    ipa_url: str,
    install_page_url: str,
    version: str,
    build_number: str,
    branch: str,
    commit: str,
    build_date: str,
    configuration: str,
    icon_url: str | None = None,
    release_notes: str = "",
) -> str:
    # Manifest URL must be percent-encoded inside itms-services (especially ?token=...)
    encoded_manifest = quote(manifest_url, safe="")
    install_href = f"itms-services://?action=download-manifest&url={encoded_manifest}"
    safe_title = html.escape(title)
    qr_html = qr_svg(install_page_url)
    icon_html = ""
    if icon_url:
        icon_html = (
            f'<img class="install-app-icon" src="{html.escape(icon_url)}" '
            f'alt="" width="72" height="72">\n      '
        )
    badge_html = _configuration_badge(configuration)
    version_label = f"{version} ({build_number})"
    meta_rows = "".join(
        [
            _meta_row("Version", version_label),
            _meta_row("Branch", branch),
            _meta_row("Commit", commit),
            _meta_row("Built", _format_build_date(build_date)),
        ]
    )
    notes_html = _release_notes_block(release_notes)
    return f"""<!DOCTYPE html>
<html lang="en">
{base_head(f"{title} — Install", narrow=True)}
<body>
  <main class="page">
    <div class="install-card">
      {icon_html}<h1>{safe_title}</h1>
      <div class="install-meta">
        {badge_html}
        <dl class="install-meta-list">
          {meta_rows}
        </dl>
      </div>
{notes_html}      <p class="muted">Open this page in Safari on your iPhone to install.</p>
      <div class="install-qr" aria-hidden="true">
        {qr_html}
        <p class="muted">Scan with iPhone camera</p>
      </div>
      <a class="btn-primary block" href="{install_href}">Install App</a>
      <p class="muted"><a class="link-accent" href="{html.escape(ipa_url)}">Download IPA</a></p>
    </div>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate manifest.plist and install.html")
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--build-dir-name", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--bundle-version", required=True)
    parser.add_argument("--ipa-filename", default="app.ipa")
    parser.add_argument("--icon-filename", default="")
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-number", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--build-date", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--release-notes", default="")
    parser.add_argument("--access-token", default="")
    args = parser.parse_args()

    build_dir = args.build_dir
    build_dir.mkdir(parents=True, exist_ok=True)

    base = args.base_url.rstrip("/")
    rel = f"{args.project_id}/{args.build_dir_name}"
    token = args.access_token or None
    encoded_ipa = quote(args.ipa_filename, safe="")
    ipa_url = with_access_token(f"{base}/{rel}/{encoded_ipa}", token)
    manifest_url = with_access_token(f"{base}/{rel}/manifest.plist", token)
    install_page_url = with_access_token(f"{base}/{rel}/install.html", token)
    icon_url = None
    if args.icon_filename:
        encoded_icon = quote(args.icon_filename, safe="")
        icon_url = with_access_token(f"{base}/{rel}/{encoded_icon}", token)

    manifest_bytes = build_manifest(
        title=args.display_name,
        bundle_id=args.bundle_id,
        bundle_version=args.bundle_version,
        ipa_url=ipa_url,
    )
    manifest_path = build_dir / "manifest.plist"
    manifest_path.write_bytes(manifest_bytes)

    # Validate plist parses
    try:
        plistlib.loads(manifest_path.read_bytes())
    except ET.ParseError as exc:
        print(f"Invalid manifest generated: {exc}", file=sys.stderr)
        return 70

    install_path = build_dir / "install.html"
    install_path.write_text(
        build_install_html(
            title=args.display_name,
            manifest_url=manifest_url,
            ipa_url=ipa_url,
            install_page_url=install_page_url,
            version=args.version,
            build_number=args.build_number,
            branch=args.branch,
            commit=args.commit,
            build_date=args.build_date,
            configuration=args.configuration,
            icon_url=icon_url,
            release_notes=args.release_notes,
        ),
        encoding="utf-8",
    )

    print(manifest_path)
    print(install_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
