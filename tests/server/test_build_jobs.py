"""Tests for server/build_jobs.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from build_jobs import (
    BuildJobError,
    active_job_for_project,
    create_job,
    enrich_job_with_progress,
    is_build_locked,
    log_path,
    parse_job_stage,
    progress_pct_for_job,
    read_job,
    schedule_job,
    stage_label,
    validate_trigger_request,
)


def test_validate_trigger_request_accepts_defaults() -> None:
    fields = validate_trigger_request(project_id="my-app")
    assert fields["git_mode"] == "auto"
    assert fields["branch"] == ""
    assert fields["sync_strategy"] == "match_remote"
    assert fields["sync_before_build"] is True
    assert fields["allow_stale_build"] is False


def test_validate_trigger_request_rejects_bad_sync_strategy() -> None:
    with pytest.raises(BuildJobError, match="invalid sync_strategy"):
        validate_trigger_request(project_id="my-app", sync_strategy="invalid")


def test_validate_trigger_request_rejects_bad_branch() -> None:
    with pytest.raises(BuildJobError, match="invalid branch"):
        validate_trigger_request(project_id="my-app", branch="../main")


def test_create_and_read_job(tmp_path: Path) -> None:
    job = create_job(
        tmp_path,
        project_id="my-app",
        branch="feature/x",
        git_mode="worktree",
        allowed_projects={"my-app"},
    )
    assert job["status"] == "queued"
    loaded = read_job(tmp_path, job["id"])
    assert loaded is not None
    assert loaded["branch"] == "feature/x"
    assert loaded["git_mode"] == "worktree"


def test_active_job_for_project(tmp_path: Path) -> None:
    job = create_job(tmp_path, project_id="my-app", allowed_projects={"my-app"})
    assert active_job_for_project(tmp_path, "my-app") is not None
    assert active_job_for_project(tmp_path, "other") is None


def test_is_build_locked(tmp_path: Path) -> None:
    ota = tmp_path / "OTA-Builds"
    ota.mkdir()
    lock = ota / ".lock-my-app"
    lock.mkdir()
    assert is_build_locked(ota, "my-app") is True
    assert is_build_locked(ota, "other") is False


def test_schedule_job_spawns_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "scripts" / "run_build_job.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    popen_mock = MagicMock()
    monkeypatch.setattr("build_jobs.subprocess.Popen", popen_mock)

    schedule_job(tmp_path, "20260101-120000-my-app")

    popen_mock.assert_called_once()
    args = popen_mock.call_args[0][0]
    assert "run_build_job.sh" in args[2]


def test_parse_job_stage_reads_last_marker(tmp_path: Path) -> None:
    log_file = tmp_path / "job.log"
    log_file.write_text(
        "[stage] resolving_spm\n[2026-01-01] log line\n[stage] archiving\n",
        encoding="utf-8",
    )
    assert parse_job_stage(log_file) == "archiving"


def test_enrich_job_with_progress_from_log(tmp_path: Path) -> None:
    job = create_job(tmp_path, project_id="my-app", allowed_projects={"my-app"})
    log_file = log_path(tmp_path, job["id"])
    log_file.write_text("[stage] exporting\n", encoding="utf-8")
    enriched = enrich_job_with_progress(tmp_path, job)
    assert enriched["stage"] == "exporting"
    assert enriched["stage_label"] == "Exporting IPA"
    assert enriched["progress_pct"] == 68


def test_stage_label_fallback() -> None:
    assert stage_label("archiving") == "Archiving"
    assert stage_label("custom_stage") == "Custom Stage"


def test_progress_pct_for_job_success() -> None:
    assert progress_pct_for_job({"status": "success"}, None) == 100
