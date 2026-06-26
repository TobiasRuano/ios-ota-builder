#!/usr/bin/env python3
"""Remove old OTA builds per retention policy."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path


def cleanup_project(project_dir: Path, *, keep: int, max_age_days: int) -> list[Path]:
    removed: list[Path] = []
    if not project_dir.is_dir():
        return removed

    builds = sorted(
        [p for p in project_dir.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    now = time.time()
    max_age_secs = max_age_days * 86400

    for idx, build_dir in enumerate(builds):
        age = now - build_dir.stat().st_mtime
        too_old = age > max_age_secs
        over_keep = idx >= keep
        if too_old or over_keep:
            shutil.rmtree(build_dir)
            removed.append(build_dir)

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup old OTA builds")
    parser.add_argument("--ota-dir", required=True, type=Path)
    parser.add_argument("--keep", type=int, default=10)
    parser.add_argument("--max-age-days", type=int, default=14)
    args = parser.parse_args()

    removed_all: list[Path] = []
    if not args.ota_dir.is_dir():
        return 0

    for project_dir in args.ota_dir.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        if project_dir.name in ("builds.json",):
            continue
        removed_all.extend(
            cleanup_project(project_dir, keep=args.keep, max_age_days=args.max_age_days)
        )

    for path in removed_all:
        print(f"removed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
