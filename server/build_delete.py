"""Safe deletion of OTA build directories."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
BUILD_DIR_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class BuildDeleteError(ValueError):
    pass


def delete_build(
    ota_dir: Path,
    project_id: str,
    build_dir: str,
    *,
    allowed_projects: set[str] | None = None,
) -> Path:
    if not PROJECT_ID_RE.match(project_id):
        raise BuildDeleteError("invalid project_id")
    if not BUILD_DIR_RE.match(build_dir):
        raise BuildDeleteError("invalid build_dir")
    if allowed_projects is not None and project_id not in allowed_projects:
        raise BuildDeleteError("unknown project_id")

    ota_root = ota_dir.resolve()
    project_root = (ota_root / project_id).resolve()
    if not str(project_root).startswith(str(ota_root) + os.sep):
        raise BuildDeleteError("invalid project path")

    target = (project_root / build_dir).resolve()
    if not str(target).startswith(str(project_root) + os.sep):
        raise BuildDeleteError("invalid build path")
    if not target.is_dir():
        raise BuildDeleteError("build not found")

    shutil.rmtree(target)
    return target
