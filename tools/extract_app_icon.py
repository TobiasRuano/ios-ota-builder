#!/usr/bin/env python3
"""Extract an app icon PNG from an Xcode archive (.xcarchive).

Priority order (Icon Composer first):
1. Assets.car via CFBundleIconName + iconutil / assetutil
2. Loose AppIcon*.png files in the app bundle (legacy appiconset)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    except FileNotFoundError:
        return None


def _warn(message: str) -> None:
    print(f"extract_app_icon: {message}", file=sys.stderr)


def _plist_value(plist_path: Path, key: str) -> str | None:
    result = _run(
        ["/usr/libexec/PlistBuddy", "-c", f"Print {key}", str(plist_path)],
    )
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def find_main_app_bundle(archive_path: Path) -> Path | None:
    apps_dir = archive_path / "Products" / "Applications"
    if not apps_dir.is_dir():
        return None

    plists = sorted(apps_dir.rglob("Info.plist"))
    for plist in plists:
        rel = plist.relative_to(apps_dir)
        parts = rel.parts
        if len(parts) < 2 or parts[-1] != "Info.plist":
            continue
        if ".appex" in parts or ".framework" in parts:
            continue
        app_bundle = plist.parent
        if app_bundle.suffix == ".app":
            return app_bundle
    return None


def read_icon_name(info_plist: Path) -> str:
    for key in (
        "CFBundleIconName",
        "CFBundleIcons:CFBundlePrimaryIcon:CFBundleIconName",
    ):
        value = _plist_value(info_plist, key)
        if value:
            return value
    return "AppIcon"


def find_assets_car(app_bundle: Path) -> Path | None:
    candidates = [
        app_bundle / "Assets.car",
        app_bundle / "Contents" / "Resources" / "Assets.car",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _image_dimensions(path: Path) -> tuple[int, int]:
    if not shutil.which("sips"):
        return (0, 0)
    result = _run(["sips", "-g", "pixelWidth", str(path)])
    height = _run(["sips", "-g", "pixelHeight", str(path)])
    if result is None or height is None or result.returncode != 0 or height.returncode != 0:
        return (0, 0)

    def _parse_dim(output: str, key: str) -> int:
        for line in output.splitlines():
            if key in line:
                try:
                    return int(line.split(":")[-1].strip())
                except ValueError:
                    return 0
        return 0

    return (_parse_dim(result.stdout, "pixelWidth"), _parse_dim(height.stdout, "pixelHeight"))


def _largest_png(paths: list[Path]) -> Path | None:
    best: Path | None = None
    best_area = -1
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        w, h = _image_dimensions(path)
        area = w * h if w and h else path.stat().st_size
        if area > best_area:
            best_area = area
            best = path
    return best


def _resize_to_png(source: Path, output: Path, size: int = 180) -> bool:
    if not shutil.which("sips"):
        _warn("sips not available; cannot normalize icon")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    shutil.copy2(source, output)
    result = _run(["sips", "-z", str(size), str(size), str(output)])
    if result is None or result.returncode != 0:
        detail = result.stderr.strip() if result else "sips not available"
        _warn(f"sips resize failed: {detail}")
        if output.exists():
            output.unlink()
        return False
    return output.is_file()


def _iconutil_iconset(car_path: Path, icon_name: str, dest_dir: Path) -> Path | None:
    if not shutil.which("iconutil"):
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    if any(dest_dir.iterdir()):
        for child in dest_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    result = _run(["iconutil", "-c", "iconset", str(car_path), icon_name, "-o", str(dest_dir)])
    if result is None or result.returncode != 0:
        return None
    pngs = list(dest_dir.rglob("*.png"))
    return _largest_png(pngs)


def _assetutil_info(car_path: Path) -> list[dict]:
    if not shutil.which("xcrun"):
        return []
    for cmd in (
        ["xcrun", "assetutil", "--info", str(car_path)],
        ["xcrun", "--sdk", "iphoneos", "assetutil", "--info", str(car_path)],
    ):
        result = _run(cmd)
        if result is None or result.returncode != 0 or not result.stdout.strip():
            continue
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _score_icon_entry(entry: dict) -> int:
    width = int(entry.get("PixelWidth") or entry.get("Width") or 0)
    height = int(entry.get("PixelHeight") or entry.get("Height") or 0)
    scale = int(entry.get("Scale") or 1)
    idiom = str(entry.get("Idiom") or "").lower()
    idiom_bonus = 10 if idiom in {"phone", "universal", "ipad"} else 0
    return width * height * scale * scale + idiom_bonus


def _matching_icon_entries(entries: list[dict], icon_name: str) -> list[dict]:
    matches: list[dict] = []
    icon_lower = icon_name.lower()
    for entry in entries:
        name = str(entry.get("Name") or "")
        asset_type = str(entry.get("AssetType") or "")
        if not name:
            continue
        name_match = name == icon_name or name.lower() == icon_lower
        type_match = "icon" in asset_type.lower()
        has_pixels = any(k in entry for k in ("PixelWidth", "PixelHeight", "Width", "Height"))
        if (name_match or type_match) and has_pixels:
            matches.append(entry)
    if matches:
        return matches
    for entry in entries:
        asset_type = str(entry.get("AssetType") or "")
        if "icon" in asset_type.lower() and any(
            k in entry for k in ("PixelWidth", "PixelHeight", "Width", "Height")
        ):
            matches.append(entry)
    return matches


def _extract_from_assets_car(car_path: Path, icon_name: str, tmp_dir: Path) -> Path | None:
    iconset_dir = tmp_dir / "iconset"
    png = _iconutil_iconset(car_path, icon_name, iconset_dir)
    if png is not None:
        return png

    entries = _assetutil_info(car_path)
    if not entries:
        return None

    candidates = _matching_icon_entries(entries, icon_name)
    if not candidates:
        return None

    candidates.sort(key=_score_icon_entry, reverse=True)
    tried: set[str] = set()
    for entry in candidates:
        for key in ("Name", "RenditionName"):
            candidate_name = str(entry.get(key) or "")
            if not candidate_name or candidate_name in tried:
                continue
            tried.add(candidate_name)
            png = _iconutil_iconset(car_path, candidate_name, tmp_dir / f"iconset-{len(tried)}")
            if png is not None:
                return png
    return None


def _extract_loose_pngs(app_bundle: Path) -> Path | None:
    patterns = ("AppIcon*.png", "Icon*.png", "icon.png")
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(app_bundle.glob(pattern))
    return _largest_png(candidates)


def extract_icon(archive_path: Path, output: Path) -> str | None:
    app_bundle = find_main_app_bundle(archive_path)
    if app_bundle is None:
        _warn("no main .app bundle found in archive")
        return None

    info_plist = app_bundle / "Info.plist"
    icon_name = read_icon_name(info_plist) if info_plist.is_file() else "AppIcon"

    with tempfile.TemporaryDirectory(prefix="ota-icon-") as tmp:
        tmp_dir = Path(tmp)

        car_path = find_assets_car(app_bundle)
        if car_path is not None:
            png = _extract_from_assets_car(car_path, icon_name, tmp_dir)
            if png is not None and _resize_to_png(png, output):
                return "iconutil" if png.parent.name == "iconset" else "assetutil"

        png = _extract_loose_pngs(app_bundle)
        if png is not None and _resize_to_png(png, output):
            return "loose-png"

    _warn("no extractable app icon found")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract app icon PNG from an Xcode archive")
    parser.add_argument("--archive", required=True, type=Path, help="Path to app.xcarchive")
    parser.add_argument("--output", required=True, type=Path, help="Destination icon.png path")
    args = parser.parse_args()

    archive_path = args.archive.resolve()
    output_path = args.output.resolve()

    if not archive_path.is_dir():
        print(f"Archive not found: {archive_path}", file=sys.stderr)
        return 1

    strategy = extract_icon(archive_path, output_path)
    if strategy:
        print(f"Wrote {output_path} ({strategy})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
