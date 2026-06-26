"""Tests for server/static_server.py isolated methods."""

from __future__ import annotations

import json
import os
from io import BytesIO
from types import SimpleNamespace
import pytest

from static_server import OTAHandler


class HandlerHarness:
    """Minimal harness to exercise OTAHandler without starting a server."""

    def __init__(self, path: str = "/", *, body: bytes = b"") -> None:
        self.handler = OTAHandler.__new__(OTAHandler)
        self.handler.path = path
        self.handler.headers = SimpleNamespace(get=lambda key, default="": {
            "Content-Length": str(len(body)),
        }.get(key, default))
        self.handler.rfile = BytesIO(body)
        self.handler.wfile = BytesIO()
        self.handler.responses = {(404, "Not Found"): ("Not Found", "Not found")}

    def route_path(self) -> str:
        return self.handler._route_path()


def test_is_public_path() -> None:
    assert OTAHandler._is_public_path("/health") is True
    assert OTAHandler._is_public_path("/") is False
    assert OTAHandler._is_public_path("/builds.json") is False


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
