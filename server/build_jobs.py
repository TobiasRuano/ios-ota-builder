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
) -> dict[str, str]:
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
    return {
        "project_id": project_id,
        "branch": branch,
        "git_mode": mode,
        "configuration": config,
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
    allowed_projects: set[str] | None = None,
) -> dict:
    fields = validate_trigger_request(
        project_id=project_id,
        branch=branch,
        git_mode=git_mode,
        configuration=configuration,
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
        "status": "queued",
        "created_at": _now_iso(),
        "started_at": "",
        "finished_at": "",
        "workspace_path": "",
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
            return job
    return None


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
