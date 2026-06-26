"""Tests for tools/diagnose_xcodebuild_log.py."""

from __future__ import annotations

from pathlib import Path

from diagnose_xcodebuild_log import (
    diagnose,
    extract_error_lines,
    read_ota_failure_reason,
)


def test_extract_error_lines_deduplicates() -> None:
    log = "\n".join(
        [
            "note: building",
            "error: Signing for MyApp failed",
            "error: Signing for MyApp failed",
            "ARCHIVE FAILED",
        ]
    )
    lines = extract_error_lines(log)
    assert lines == ["error: Signing for MyApp failed", "ARCHIVE FAILED"]


def test_diagnose_provisioning_error() -> None:
  log = Path(__file__).resolve().parent.parent.joinpath(
      "fixtures", "provisioning_error.log"
  ).read_text(encoding="utf-8")
  category, summary, suggestion, errors = diagnose(log, "archive")
  assert category == "provisioning"
  assert "provisioning profile" in suggestion.lower() or "Provisioning" in suggestion
  assert errors


def test_diagnose_spm_dependency_error() -> None:
    log = Path(__file__).resolve().parent.parent.joinpath(
        "fixtures", "spm_error.log"
    ).read_text(encoding="utf-8")
    category, summary, suggestion, errors = diagnose(log, "archive")
    assert category == "dependencies"
    assert "SPM" in suggestion or "dependency" in suggestion.lower()
    assert errors


def test_read_ota_failure_reason(tmp_path: Path) -> None:
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / ".ota_failure_reason").write_text(
        "CFBundleVersion must be an integer\nUse integer build numbers only.\n",
        encoding="utf-8",
    )
    result = read_ota_failure_reason(build_dir)
    assert result is not None
    category, summary, suggestion = result
    assert category == "archive"
    assert "CFBundleVersion" in summary
    assert "integer" in suggestion
