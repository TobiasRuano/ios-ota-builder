"""Tests for F14 per-project build lock (scripts/lib/common.sh)."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = REPO_ROOT / "scripts" / "lib" / "common.sh"
EC_ENVIRONMENT = 10


def _source_common() -> str:
    return f'source "{COMMON_SH}"'


def run_bash(
    script: str,
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    full_env["OTA_BUILDER_ROOT"] = str(REPO_ROOT)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        ["bash", "-c", script],
        env=full_env,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"bash failed ({proc.returncode}):\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


@pytest.fixture
def lock_env(tmp_path: Path) -> dict[str, str]:
    builds = tmp_path / "builds"
    builds.mkdir()
    return {
        "OTA_BUILDS_DIR": str(builds),
    }


def test_build_lock_dir_path(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export PROJECT_ID=my-app
        build_lock_dir
        """
    )
    proc = run_bash(script, env=lock_env)
    assert proc.stdout.strip() == f"{lock_env['OTA_BUILDS_DIR']}/.lock-my-app"


def test_different_project_ids_acquire_separate_locks(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=fail
        export PROJECT_ID=proj-a
        acquire_build_lock
        lock_a="$(build_lock_dir)"
        export PROJECT_ID=proj-b
        acquire_build_lock
        lock_b="$(build_lock_dir)"
        [[ -d "$lock_a" && -d "$lock_b" && "$lock_a" != "$lock_b" ]]
        export PROJECT_ID=proj-b
        release_build_lock
        export PROJECT_ID=proj-a
        release_build_lock
        """
    )
    run_bash(script, env=lock_env)


def test_fail_mode_blocks_second_build_for_same_project(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=fail
        export PROJECT_ID=my-app
        acquire_build_lock
        (
          export PROJECT_ID=my-app OTA_BUILD_LOCK=fail
          acquire_build_lock 2>/dev/null
        ) && exit 1
        release_build_lock
        """
    )
    proc = run_bash(script, env=lock_env, check=False)
    assert proc.returncode == 0


def test_fail_mode_reports_holder_pid(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=fail
        export PROJECT_ID=my-app
        acquire_build_lock
        holder_pid="$(cat "$(build_lock_dir)/pid")"
        (
          export PROJECT_ID=my-app OTA_BUILD_LOCK=fail
          acquire_build_lock
        ) 2>err.log || true
        grep -Fq "pid $holder_pid" err.log
        release_build_lock
        """
    )
    run_bash(script, env=lock_env)


def test_wait_mode_acquires_after_release(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=wait
        export OTA_BUILD_LOCK_TIMEOUT=5
        export PROJECT_ID=my-app
        acquire_build_lock
        (
          export PROJECT_ID=my-app OTA_BUILD_LOCK=wait OTA_BUILD_LOCK_TIMEOUT=5
          sleep 0.3
          acquire_build_lock
          release_build_lock
        ) &
        wait_pid=$!
        sleep 0.05
        release_build_lock
        wait "$wait_pid"
        """
    )
    run_bash(script, env=lock_env)


def test_release_build_lock_removes_directory(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=fail
        export PROJECT_ID=my-app
        acquire_build_lock
        lock_dir="$(build_lock_dir)"
        release_build_lock
        [[ ! -d "$lock_dir" ]]
        """
    )
    run_bash(script, env=lock_env)


def test_stale_lock_with_dead_pid_is_replaced(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=fail
        export PROJECT_ID=my-app
        stale_dir="$(build_lock_dir)"
        mkdir -p "$stale_dir"
        printf '999999\\n' >"$stale_dir/pid"
        acquire_build_lock
        [[ -f "$stale_dir/pid" && "$(tr -d '[:space:]' <"$stale_dir/pid")" == "$$" ]]
        release_build_lock
        """
    )
    run_bash(script, env=lock_env)


def test_invalid_ota_build_lock_exits_with_environment_code(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=invalid
        export PROJECT_ID=my-app
        acquire_build_lock
        """
    )
    proc = run_bash(script, env=lock_env, check=False)
    assert proc.returncode == EC_ENVIRONMENT
    assert "Invalid OTA_BUILD_LOCK" in proc.stderr


def test_wait_mode_times_out(lock_env: dict[str, str]) -> None:
    script = textwrap.dedent(
        f"""
        {_source_common()}
        export OTA_BUILD_LOCK=fail
        export PROJECT_ID=my-app
        acquire_build_lock
        (
          export PROJECT_ID=my-app OTA_BUILD_LOCK=wait OTA_BUILD_LOCK_TIMEOUT=1
          acquire_build_lock
        )
        """
    )
    proc = run_bash(script, env=lock_env, check=False)
    assert proc.returncode == EC_ENVIRONMENT
    assert "Timed out waiting for build lock" in proc.stderr
    release = run_bash(
        textwrap.dedent(
            f"""
            {_source_common()}
            export PROJECT_ID=my-app
            export BUILD_LOCK_DIR="$(printf '%s/.lock-my-app' "$OTA_BUILDS_DIR")"
            export BUILD_LOCK_ACQUIRED=true
            release_build_lock
            """
        ),
        env=lock_env,
    )
    assert release.returncode == 0
