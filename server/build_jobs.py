"""Build job queue for dashboard-triggered OTA builds."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
JOB_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
BRANCH_RE = re.compile(r"^[a-zA-Z0-9/_.-]+$")
GIT_MODES = frozenset({"auto", "checkout", "stash_checkout", "worktree"})
SYNC_STRATEGIES = frozenset({"match_remote", "fast_forward", "recreate_worktree"})

STAGE_MARKER_RE = re.compile(r"^\[stage\]\s+(\S+)", re.MULTILINE)

STAGE_PROGRESS: dict[str, int] = {
    "queued": 5,
    "preparing": 10,
    "git_sync": 12,
    "environment": 12,
    "resolving_spm": 28,
    "archiving": 50,
    "exporting": 68,
    "publishing": 85,
    "indexing": 95,
}

STAGE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "preparing": "Preparing",
    "git_sync": "Syncing git workspace",
    "environment": "Environment checks",
    "resolving_spm": "Resolving dependencies",
    "archiving": "Archiving",
    "exporting": "Exporting IPA",
    "publishing": "Publishing",
    "indexing": "Updating index",
}

JOB_STATUS_STAGE: dict[str, str] = {
    "queued": "queued",
    "preparing": "preparing",
    "building": "environment",
}


class BuildJobError(ValueError):
    pass


def jobs_dir(root: Path) -> Path:
    return root / ".server" / "build-jobs"


def _job_path(root: Path, job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id):
        raise BuildJobError("invalid job_id")
    return jobs_dir(root) / f"{job_id}.json"


def log_path(root: Path, job_id: str) -> Path:
    return jobs_dir(root) / f"{job_id}.log"


def is_build_locked(ota_dir: Path, project_id: str) -> bool:
    lock_dir = ota_dir / f".lock-{project_id}"
    return lock_dir.is_dir()


def validate_trigger_request(
    *,
    project_id: str,
    branch: str = "",
    git_mode: str = "auto",
    configuration: str = "",
    sync_strategy: str = "",
    sync_before_build: bool = True,
    allow_stale_build: bool = False,
) -> dict[str, str | bool]:
    if not PROJECT_ID_RE.match(project_id):
        raise BuildJobError("invalid project_id")
    branch = branch.strip()
    if branch and not BRANCH_RE.match(branch):
        raise BuildJobError("invalid branch")
    if branch.startswith(".") or ".." in branch:
        raise BuildJobError("invalid branch")
    mode = git_mode.strip() or "auto"
    if mode not in GIT_MODES:
        raise BuildJobError("invalid git_mode")
    config = configuration.strip()
    if config and config not in {"Debug", "Release"}:
        raise BuildJobError("invalid configuration")
    strategy = sync_strategy.strip() or "match_remote"
    if strategy not in SYNC_STRATEGIES:
        raise BuildJobError("invalid sync_strategy")
    return {
        "project_id": project_id,
        "branch": branch,
        "git_mode": mode,
        "configuration": config,
        "sync_strategy": strategy,
        "sync_before_build": sync_before_build,
        "allow_stale_build": allow_stale_build,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_job(
    root: Path,
    *,
    project_id: str,
    branch: str = "",
    git_mode: str = "auto",
    configuration: str = "",
    sync_strategy: str = "",
    sync_before_build: bool = True,
    allow_stale_build: bool = False,
    allowed_projects: set[str] | None = None,
) -> dict:
    fields = validate_trigger_request(
        project_id=project_id,
        branch=branch,
        git_mode=git_mode,
        configuration=configuration,
        sync_strategy=sync_strategy,
        sync_before_build=sync_before_build,
        allow_stale_build=allow_stale_build,
    )
    if allowed_projects is not None and project_id not in allowed_projects:
        raise BuildJobError("unknown project_id")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_id = f"{stamp}-{project_id}"
    directory = jobs_dir(root)
    directory.mkdir(parents=True, exist_ok=True)

    job = {
        "id": job_id,
        "project_id": project_id,
        "branch": fields["branch"],
        "git_mode": fields["git_mode"],
        "configuration": fields["configuration"],
        "sync_strategy": fields["sync_strategy"],
        "sync_before_build": fields["sync_before_build"],
        "allow_stale_build": fields["allow_stale_build"],
        "status": "queued",
        "created_at": _now_iso(),
        "started_at": "",
        "finished_at": "",
        "workspace_path": "",
        "workspace_commit": "",
        "workspace_commit_short": "",
        "remote_commit": "",
        "build_dir": "",
        "error": "",
        "log_path": f".server/build-jobs/{job_id}.log",
    }
    _job_path(root, job_id).write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    log_path(root, job_id).touch()
    return job


def read_job(root: Path, job_id: str) -> dict | None:
    path = _job_path(root, job_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def update_job(root: Path, job_id: str, **fields: str) -> dict:
    job = read_job(root, job_id)
    if job is None:
        raise BuildJobError("job not found")
    job.update(fields)
    _job_path(root, job_id).write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return job


def list_jobs(root: Path, *, project_id: str = "", limit: int = 20) -> list[dict]:
    directory = jobs_dir(root)
    if not directory.is_dir():
        return []
    jobs: list[dict] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if project_id and job.get("project_id") != project_id:
            continue
        jobs.append(job)
        if len(jobs) >= limit:
            break
    return jobs


def active_job_for_project(root: Path, project_id: str) -> dict | None:
    for job in list_jobs(root, project_id=project_id, limit=50):
        if job.get("status") in {"queued", "preparing", "building"}:
            return enrich_job_with_progress(root, job)
    return None


def parse_job_stage(log_file: Path) -> str | None:
    if not log_file.is_file():
        return None
    content = log_file.read_text(encoding="utf-8", errors="replace")
    tail = content[-50000:] if len(content) > 50000 else content
    matches = STAGE_MARKER_RE.findall(tail)
    return matches[-1] if matches else None


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.replace("_", " ").title())


def progress_pct_for_job(job: dict, stage: str | None) -> int:
    status = job.get("status", "")
    if status == "success":
        return 100
    if status == "failed":
        if stage:
            return STAGE_PROGRESS.get(stage, 10)
        return 10
    if stage:
        return STAGE_PROGRESS.get(stage, 10)
    return STAGE_PROGRESS.get(JOB_STATUS_STAGE.get(status, ""), 5)


def _failure_stage_from_summary(root: Path, project_id: str) -> str | None:
    ota_dir = root / "OTA-Builds" / project_id
    if not ota_dir.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for build_dir in ota_dir.iterdir():
        if not build_dir.is_dir():
            continue
        summary_path = build_dir / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if summary.get("status") != "failure":
            continue
        try:
            mtime = summary_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, build_dir))
    if not candidates:
        return None
    _, latest = max(candidates, key=lambda item: item[0])
    try:
        summary = json.loads((latest / "summary.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    stage = summary.get("stage")
    return stage if isinstance(stage, str) and stage else None


def enrich_job_with_progress(root: Path, job: dict) -> dict:
    enriched = dict(job)
    status = job.get("status", "")
    stage: str | None = None

    log_file = log_path(root, job["id"])
    if status in {"queued", "preparing", "building", "failed"}:
        stage = parse_job_stage(log_file)
    if not stage and status in JOB_STATUS_STAGE:
        stage = JOB_STATUS_STAGE[status]
    if status == "failed" and not stage:
        stage = _failure_stage_from_summary(root, job.get("project_id", ""))

    if stage:
        enriched["stage"] = stage
        enriched["stage_label"] = stage_label(stage)
    enriched["progress_pct"] = progress_pct_for_job(job, stage)
    return enriched


def schedule_job(root: Path, job_id: str) -> None:
    script = (root / "scripts" / "run_build_job.sh").resolve()
    if not script.is_file():
        raise FileNotFoundError(f"build job runner not found: {script}")

    jobs_dir(root).mkdir(parents=True, exist_ok=True)
    log_path(root, job_id).touch()

    subprocess.Popen(
        ["bash", "-c", f"exec {script} {job_id}"],
        cwd=root,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
