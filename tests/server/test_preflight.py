"""Tests for server/preflight.py and preflight API handler."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from preflight import (
    http_status_for_preflight,
    run_preflight,
    validate_preflight_request,
)
from static_server import OTAHandler


class HandlerHarness:
    def __init__(self, path: str = "/", *, body: bytes = b"") -> None:
        self.handler = OTAHandler.__new__(OTAHandler)
        self.handler.path = path
        self.handler.headers = SimpleNamespace(
            get=lambda key, default="": {
                "Content-Length": str(len(body)),
            }.get(key, default)
        )
        self.handler.rfile = BytesIO(body)
        self.handler.wfile = BytesIO()


def test_validate_preflight_request_rejects_invalid_project_id() -> None:
    with pytest.raises(Exception, match="invalid project_id"):
        validate_preflight_request(project_id="../evil")


def test_validate_preflight_request_unknown_project() -> None:
    with pytest.raises(Exception, match="unknown project_id"):
        validate_preflight_request(project_id="my-app", allowed_projects={"other"})


def test_http_status_for_preflight_mapping() -> None:
    assert http_status_for_preflight(0, {"status": "ok"}) == 200
    assert http_status_for_preflight(10, {"status": "failed"}) == 422
    assert http_status_for_preflight(1, {"status": "ok"}) == 500


def test_run_preflight_parses_stdout_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "agent_build_ota.sh"
    script.write_text(
        '#!/usr/bin/env bash\nprintf \'{"status":"ok","checks":[]}\\n\'\n',
        encoding="utf-8",
    )
    script.chmod(0o755)

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"status":"ok","checks":[]}\n', stderr="")

    monkeypatch.setattr("preflight.subprocess.run", fake_run)
    exit_code, payload = run_preflight(tmp_path, "my-app")
    assert exit_code == 0
    assert payload["status"] == "ok"


def test_run_preflight_invalid_json_returns_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "agent_build_ota.sh"
    script.write_text("#!/usr/bin/env bash\necho not-json\n", encoding="utf-8")
    script.chmod(0o755)

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=10, stdout="not-json\n", stderr="boom")

    monkeypatch.setattr("preflight.subprocess.run", fake_run)
    status, payload = run_preflight(tmp_path, "my-app")
    assert status == 500
    assert payload["status"] == "failed"


def test_handle_build_preflight_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"display_name": "My App", "path": str(tmp_path)}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OTA_PROJECTS_JSON", str(projects_json))

    payload = {
        "status": "ok",
        "project": "my-app",
        "checks": [{"name": "signing", "status": "ok"}],
        "duration_seconds": 2,
    }

    monkeypatch.setattr("static_server.run_preflight", lambda *a, **k: (0, payload))
    monkeypatch.setattr("static_server.csrf_valid", lambda *a, **k: True)

    harness = HandlerHarness(
        "/api/builds/preflight?token=secret",
        body=b"project_id=my-app",
    )
    sent: list[tuple[int, bytes]] = []

    def capture_send(status: int, body: bytes, content_type: str) -> None:
        sent.append((status, body))

    harness.handler._send_bytes = capture_send  # type: ignore[method-assign]
    harness.handler._projects = lambda: {"my-app": {}}  # type: ignore[method-assign]
    harness.handler._handle_build_preflight()

    assert sent[0][0] == 200
    body = json.loads(sent[0][1].decode("utf-8"))
    assert body["status"] == "ok"
    assert body["checks"][0]["name"] == "signing"


def test_handle_build_preflight_failed_check_returns_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"display_name": "My App", "path": str(tmp_path)}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OTA_PROJECTS_JSON", str(projects_json))

    payload = {
        "status": "failed",
        "project": "my-app",
        "checks": [{"name": "signing", "status": "failed", "message": "no cert"}],
        "duration_seconds": 1,
    }

    monkeypatch.setattr("static_server.run_preflight", lambda *a, **k: (10, payload))
    monkeypatch.setattr("static_server.csrf_valid", lambda *a, **k: True)

    harness = HandlerHarness(
        "/api/builds/preflight?token=secret",
        body=b"project_id=my-app",
    )
    sent: list[tuple[int, bytes]] = []

    def capture_send(status: int, body: bytes, content_type: str) -> None:
        sent.append((status, body))

    harness.handler._send_bytes = capture_send  # type: ignore[method-assign]
    harness.handler._projects = lambda: {"my-app": {}}  # type: ignore[method-assign]
    harness.handler._handle_build_preflight()

    assert sent[0][0] == 422
    body = json.loads(sent[0][1].decode("utf-8"))
    assert body["checks"][0]["status"] == "failed"


def test_handle_build_preflight_rejects_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("static_server.csrf_valid", lambda *a, **k: False)

    harness = HandlerHarness(
        "/api/builds/preflight?token=secret",
        body=b"project_id=my-app",
    )
    sent: list[tuple[int, bytes]] = []

    def capture_send(status: int, body: bytes, content_type: str) -> None:
        sent.append((status, body))

    harness.handler._send_bytes = capture_send  # type: ignore[method-assign]
    harness.handler._handle_build_preflight()

    assert sent[0][0] == 403
