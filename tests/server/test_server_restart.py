"""Tests for server/server_restart.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server_restart import schedule_restart


def test_schedule_restart_spawns_background_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    script = root / "server" / "restart_server.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    popen_mock = MagicMock()
    monkeypatch.setattr("server_restart.subprocess.Popen", popen_mock)

    schedule_restart(root=root, delay_seconds=1.5)

    popen_mock.assert_called_once()
    args, kwargs = popen_mock.call_args
    assert args[0] == ["bash", "-c", f"sleep 1.5; exec {script.resolve()}"]
    assert kwargs["cwd"] == root
    assert kwargs["start_new_session"] is True


def test_schedule_restart_missing_script_raises(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(FileNotFoundError, match="restart script not found"):
        schedule_restart(root=root)
