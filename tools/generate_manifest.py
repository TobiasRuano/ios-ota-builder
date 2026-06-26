#!/usr/bin/env python3
"""Generate OTA manifest.plist and install.html for an iOS build."""

from __future__ import annotations

import argparse
import html
import plistlib
import sys
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_urls import with_access_token


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


def build_install_html(*, title: str, manifest_url: str, ipa_url: str) -> str:
    # Manifest URL must be percent-encoded inside itms-services (especially ?token=...)
    encoded_manifest = quote(manifest_url, safe="")
    install_href = f"itms-services://?action=download-manifest&url={encoded_manifest}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} — Install</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }}
    a.btn {{ display: block; text-align: center; background: #007aff; color: #fff; padding: 1rem; border-radius: 10px; text-decoration: none; font-size: 1.1rem; margin: 1.5rem 0; }}
    .meta {{ color: #666; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="meta">Open this page in Safari on your iPhone to install.</p>
  <a class="btn" href="{install_href}">Install App</a>
  <p class="meta"><a href="{html.escape(ipa_url)}">Download IPA</a></p>
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
    parser.add_argument("--access-token", default="")
    args = parser.parse_args()

    build_dir = args.build_dir
    build_dir.mkdir(parents=True, exist_ok=True)

    base = args.base_url.rstrip("/")
    rel = f"{args.project_id}/{args.build_dir_name}"
    token = args.access_token or None
    ipa_url = with_access_token(f"{base}/{rel}/app.ipa", token)
    manifest_url = with_access_token(f"{base}/{rel}/manifest.plist", token)

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
        ),
        encoding="utf-8",
    )

    print(manifest_path)
    print(install_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
