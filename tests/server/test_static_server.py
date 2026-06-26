"""Tests for server/static_server.py isolated methods."""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import pytest

from credentials import hash_password
from static_server import OTAHandler


class HandlerHarness:
    """Minimal harness to exercise OTAHandler without starting a server."""

    def __init__(
        self,
        path: str = "/",
        *,
        body: bytes = b"",
        cookie: str = "",
    ) -> None:
        self.handler = OTAHandler.__new__(OTAHandler)
        self.handler.path = path
        self.handler.headers = SimpleNamespace(get=lambda key, default="": {
            "Content-Length": str(len(body)),
            "Cookie": cookie,
        }.get(key, default))
        self.handler.rfile = BytesIO(body)
        self.handler.wfile = BytesIO()
        self.handler.responses = {(404, "Not Found"): ("Not Found", "Not found")}

    def route_path(self) -> str:
        return self.handler._route_path()


def test_is_public_path() -> None:
    assert OTAHandler._is_public_path("/health", method="GET") is True
    assert OTAHandler._is_public_path("/login", method="GET") is True
    assert OTAHandler._is_public_path("/login", method="HEAD") is True
    assert OTAHandler._is_public_path("/api/login", method="POST") is True
    assert OTAHandler._is_public_path("/", method="GET") is False
    assert OTAHandler._is_public_path("/builds.json", method="GET") is False


def test_parse_latest_project() -> None:
    handler = OTAHandler.__new__(OTAHandler)
    assert handler._parse_latest_project("/latest/my-app") == "my-app"
    assert handler._parse_latest_project("/latest/") is None
    assert handler._parse_latest_project("/latest/my-app/extra") is None
    assert handler._parse_latest_project("/other") is None


def test_parse_form_body() -> None:
    harness = HandlerHarness(body=b"project_id=my-app&build_dir=06-26-42")
    form = harness.handler._parse_form_body()
    assert form == {"project_id": "my-app", "build_dir": "06-26-42"}


def test_min_disk_mb_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTA_STATUS_MIN_DISK_MB", raising=False)
    handler = OTAHandler.__new__(OTAHandler)
    assert handler._min_disk_mb() == 5000


def test_min_disk_mb_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTA_STATUS_MIN_DISK_MB", "not-a-number")
    handler = OTAHandler.__new__(OTAHandler)
    assert handler._min_disk_mb() == 5000


def test_handle_delete_success(
    ota_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = ota_dir / "my-app" / "06-26-42"
    build.mkdir(parents=True)
    (build / "app.ipa").write_bytes(b"x")

    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"display_name": "My App"}}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("OTA_BUILDS_DIR", str(ota_dir))
    monkeypatch.setenv("OTA_PROJECTS_JSON", str(projects_json))
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "secret")

    harness = HandlerHarness(
        "/api/builds/delete",
        body=b"project_id=my-app&build_dir=06-26-42",
    )
    harness.handler.path = "/api/builds/delete?token=secret"
    harness.handler.send_response = lambda code: None  # type: ignore[method-assign]
    harness.handler.send_header = lambda *args: None  # type: ignore[method-assign]
    harness.handler.end_headers = lambda: None  # type: ignore[method-assign]

    harness.handler._handle_delete()

    assert not build.exists()


def test_handle_delete_invalid_build(
    ota_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"display_name": "My App"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OTA_BUILDS_DIR", str(ota_dir))
    monkeypatch.setenv("OTA_PROJECTS_JSON", str(projects_json))

    harness = HandlerHarness(
        "/api/builds/delete",
        body=b"project_id=my-app&build_dir=missing",
    )
    sent: list[tuple[int, bytes]] = []

    def capture_send(status: int, body: bytes, content_type: str) -> None:
        sent.append((status, body))

    harness.handler._send_bytes = capture_send  # type: ignore[method-assign]
    harness.handler._handle_delete()

    assert sent
    assert sent[0][0] == 400
    assert b"Delete failed" in sent[0][1]


def test_handle_login_sets_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = hash_password("pass123")
    monkeypatch.setenv("OTA_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "secret")

    harness = HandlerHarness(
        "/api/login",
        body=b"username=admin&password=pass123&next=%2F",
    )
    harness.handler.client_address = ("127.0.0.1", 54321)
    headers: list[tuple[str, str]] = []

    harness.handler.send_response = lambda code: None  # type: ignore[method-assign]
    harness.handler.send_header = lambda key, value: headers.append((key, value))  # type: ignore[method-assign]
    harness.handler.end_headers = lambda: None  # type: ignore[method-assign]

    harness.handler._handle_login()

    assert any(key == "Set-Cookie" and "OTA_SESSION=" in value for key, value in headers)
    assert any(key == "Location" and value == "/?token=secret" for key, value in headers)


def test_serve_dynamic_ota_artifact(
    ota_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dir = ota_dir / "my-app" / "06-26-42"
    build_dir.mkdir(parents=True)
    (build_dir / "app.ipa").write_bytes(b"ipa")
    (build_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "display_name": "My App",
                "version": "1.0",
                "build_number": "42",
                "branch": "main",
                "commit": "abc",
                "date": "2026-06-26T12:00:00Z",
                "configuration": "Release",
            }
        ),
        encoding="utf-8",
    )
    projects_json = tmp_path / "projects.json"
    projects_json.write_text(
        json.dumps({"projects": {"my-app": {"display_name": "My App", "bundle_id": "com.example.app"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OTA_BUILDS_DIR", str(ota_dir))
    monkeypatch.setenv("OTA_PROJECTS_JSON", str(projects_json))
    monkeypatch.setenv("OTA_BASE_URL", "https://ota.example.com")
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "live-token")

    harness = HandlerHarness("/my-app/06-26-42/manifest.plist?token=live-token")
    sent: list[tuple[int, bytes, str]] = []
    harness.handler._send_bytes = lambda status, body, content_type: sent.append((status, body, content_type))  # type: ignore[method-assign]

    assert harness.handler._serve_dynamic_ota_artifact("/my-app/06-26-42/manifest.plist") is True
    assert sent[0][0] == 200
    assert b"live-token" in sent[0][1]


def test_handle_restart_schedules_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduled: list[Path] = []

    def fake_schedule_restart(*, root: Path, delay_seconds: float = 1.0) -> None:
        scheduled.append(root)

    monkeypatch.setattr("static_server.schedule_restart", fake_schedule_restart)

    harness = HandlerHarness("/api/server/restart")
    sent: list[tuple[int, bytes]] = []

    def capture_send(status: int, body: bytes, content_type: str) -> None:
        sent.append((status, body))

    harness.handler._send_bytes = capture_send  # type: ignore[method-assign]
    harness.handler._handle_restart()

    assert scheduled
    assert sent[0][0] == 202
    payload = json.loads(sent[0][1].decode("utf-8"))
    assert payload["restarting"] is True


def test_handle_restart_missing_script_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_schedule_restart(*, root: Path, delay_seconds: float = 1.0) -> None:
        raise FileNotFoundError("restart script not found")

    monkeypatch.setattr("static_server.schedule_restart", fail_schedule_restart)

    harness = HandlerHarness("/api/server/restart")
    sent: list[tuple[int, bytes]] = []

    def capture_send(status: int, body: bytes, content_type: str) -> None:
        sent.append((status, body))

    harness.handler._send_bytes = capture_send  # type: ignore[method-assign]
    harness.handler._handle_restart()

    assert sent[0][0] == 500
    payload = json.loads(sent[0][1].decode("utf-8"))
    assert "restart script not found" in payload["error"]
