#!/usr/bin/env python3
"""Heuristic parser for xcodebuild logs — writes diagnostics.md."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERNS: list[tuple[str, str, str]] = [
    (
        r"error:.*[Pp]rovisioning profile",
        "provisioning",
        "Provisioning profile issue. Register device UDID in Apple Developer, then Xcode → Accounts → Download Manual Profiles.",
    ),
    (
        r"error:.*[Cc]ode [Ss]ign",
        "signing",
        "Code signing failed. Open Xcode → Settings → Accounts → Manage Certificates → add Apple Distribution.",
    ),
    (
        r"No signing certificate",
        "signing",
        "Missing signing certificate. Create Apple Distribution in Xcode Manage Certificates.",
    ),
    (
        r"error:.*Signing for",
        "signing",
        "Automatic signing failed for a target. Ensure all targets share team and have valid profiles.",
    ),
    (
        r"error:.*No such module",
        "build",
        "Missing Swift module. Check SPM resolution and import statements.",
    ),
    (
        r"could not find module",
        "build",
        "Module not found. Run dependency resolution or fix package references.",
    ),
    (
        r"error:.*unable to resolve",
        "dependencies",
        "SPM dependency resolution failed. Check network and Package.swift / project package pins.",
    ),
    (
        r"error:",
        "build",
        "Compiler or linker error. Inspect the lines below in archive.log or export.log.",
    ),
    (
        r"EXPORT FAILED",
        "export",
        "Archive export failed. Check export.log for signing or entitlement issues.",
    ),
    (
        r"ARCHIVE FAILED",
        "archive",
        "Archive step failed. Check archive.log for compile or signing errors.",
    ),
]


def read_logs(build_dir: Path) -> tuple[str, Path | None]:
    parts: list[str] = []
    primary: Path | None = None
    for name in ("export.log", "archive.log", "build.log"):
        path = build_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"=== {name} ===\n{text}")
            if primary is None and text.strip():
                primary = path
    return "\n\n".join(parts), primary


def extract_error_lines(log_text: str, limit: int = 20) -> list[str]:
    lines = []
    for line in log_text.splitlines():
        if re.search(r"error:|fatal error:|EXPORT FAILED|ARCHIVE FAILED", line, re.I):
            lines.append(line.strip())
    # Deduplicate preserving order
    seen: set[str] = set()
    unique = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[:limit]


def diagnose(log_text: str, stage: str) -> tuple[str, str, str, list[str]]:
    category = stage
    suggestion = "Review the full log in the build output directory."
    for pattern, cat, hint in PATTERNS:
        if re.search(pattern, log_text, re.MULTILINE):
            category = cat
            suggestion = hint
            break
    errors = extract_error_lines(log_text)
    summary = errors[0] if errors else f"Build failed at stage: {stage}"
    return category, summary, suggestion, errors


def write_diagnostics(
    *,
    path: Path,
    stage: str,
    project: str,
    bundle_id: str,
    team_id: str,
    category: str,
    summary: str,
    suggestion: str,
    errors: list[str],
    log_file: Path | None,
) -> None:
    lines = [
        "# Build Diagnostics",
        "",
        f"- **Stage**: {stage}",
        f"- **Category**: {category}",
        f"- **Project**: {project}",
        f"- **Bundle ID**: {bundle_id}",
        f"- **Team ID**: {team_id}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Key log lines",
        "",
    ]
    if errors:
        lines.extend(f"- `{e}`" for e in errors)
    else:
        lines.append("- No explicit error lines extracted; inspect full logs.")

    lines.extend(
        [
            "",
            "## Suggested fix",
            "",
            suggestion,
            "",
            "## Manual signing fallback",
            "",
            "1. Register iPhone UDID at [Apple Developer → Devices](https://developer.apple.com/account/resources/devices/list)",
            "2. Xcode → Settings → Accounts → Download Manual Profiles",
            "3. Xcode → Manage Certificates → + Apple Distribution",
            "4. Re-run: `agent_build_ota.sh " + project + "`",
            "",
        ]
    )

    if log_file:
        lines.extend(["## Log file", "", f"`{log_file}`", ""])

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose xcodebuild failure")
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--team-id", default="")
    args = parser.parse_args()

    log_text, primary = read_logs(args.build_dir)
    category, summary, suggestion, errors = diagnose(log_text, args.stage)

    out = args.build_dir / "diagnostics.md"
    write_diagnostics(
        path=out,
        stage=args.stage,
        project=args.project,
        bundle_id=args.bundle_id,
        team_id=args.team_id,
        category=category,
        summary=summary,
        suggestion=suggestion,
        errors=errors,
        log_file=primary,
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
