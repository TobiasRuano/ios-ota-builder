#!/usr/bin/env python3
"""Regenerate OTA-Builds/index.html and builds.json from build artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ota_index import collect_builds, load_projects_config, render_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OTA index and builds.json")
    parser.add_argument("--ota-dir", required=True, type=Path)
    parser.add_argument("--projects-json", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--access-token", default="")
    args = parser.parse_args()

    projects = load_projects_config(args.projects_json)
    if not projects and not args.projects_json.is_file():
        print(f"Missing projects config: {args.projects_json}", file=sys.stderr)
        return 80

    data = collect_builds(args.ota_dir, projects)

    builds_json_path = args.ota_dir / "builds.json"
    builds_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    index_html = render_index(data, args.base_url, args.access_token or None, enable_delete=False)
    index_path = args.ota_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    print(builds_json_path)
    print(index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
