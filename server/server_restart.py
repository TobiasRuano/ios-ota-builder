"""Schedule OTA server restart via launchd."""

from __future__ import annotations

import subprocess
from pathlib import Path


def schedule_restart(*, root: Path, delay_seconds: float = 1.0) -> None:
    """Launch restart_server.sh in background after a brief delay."""
    script = (root / "server" / "restart_server.sh").resolve()
    if not script.is_file():
        raise FileNotFoundError(f"restart script not found: {script}")

    delay = max(0.0, delay_seconds)
    cmd = f"sleep {delay}; exec {script}"
    subprocess.Popen(
        ["bash", "-c", cmd],
        cwd=root,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
