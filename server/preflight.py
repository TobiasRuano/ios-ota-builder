"""Synchronous F16 preflight for dashboard environment checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from build_jobs import BuildJobError, PROJECT_ID_RE

PREFLIGHT_TIMEOUT_SECONDS = 45
EC_ENVIRONMENT = 10


class PreflightError(ValueError):
    pass


class PreflightTimeout(PreflightError):
    pass


def validate_preflight_request(
    *,
    project_id: str,
    allowed_projects: set[str] | None = None,
) -> str:
    project_id = project_id.strip()
    if not PROJECT_ID_RE.match(project_id):
        raise BuildJobError("invalid project_id")
    if allowed_projects is not None and project_id not in allowed_projects:
        raise BuildJobError("unknown project_id")
    return project_id


def _synthetic_failure(message: str, *, project_id: str = "") -> dict:
    payload: dict = {
        "status": "failed",
        "checks": [
            {
                "name": "preflight",
                "status": "failed",
                "message": message,
            }
        ],
        "duration_seconds": 0,
    }
    if project_id:
        payload["project"] = project_id
    return payload


def run_preflight(root: Path, project_id: str) -> tuple[int, dict]:
    """Run agent_build_ota.sh --dry-run and return (exit_code, json_payload)."""
    script = (root / "agent_build_ota.sh").resolve()
    if not script.is_file():
        return 500, _synthetic_failure(f"preflight script not found: {script}", project_id=project_id)

    try:
        result = subprocess.run(
            ["bash", str(script), "--dry-run", project_id],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise PreflightTimeout("preflight timed out") from None

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            tail = stderr[-500:] if stderr else stdout[-500:]
            return 500, _synthetic_failure(
                tail or "preflight produced invalid JSON",
                project_id=project_id,
            )
    else:
        tail = stderr[-500:] if stderr else f"preflight exited with code {result.returncode}"
        return 500, _synthetic_failure(tail, project_id=project_id)

    if not isinstance(payload, dict):
        return 500, _synthetic_failure("preflight JSON must be an object", project_id=project_id)

    return result.returncode, payload


def http_status_for_preflight(exit_code: int, payload: dict) -> int:
    if exit_code == 0 and payload.get("status") == "ok":
        return 200
    if exit_code == EC_ENVIRONMENT or payload.get("status") == "failed":
        return 422
    return 500
