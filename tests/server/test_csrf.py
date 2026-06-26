"""Tests for server/csrf.py."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from credentials import hash_password
from csrf import csrf_valid, get_csrf_for_handler
from session import create_session


class MockHandler:
    def __init__(
        self,
        path: str = "/",
        *,
        authorization: str = "",
        cookie: str = "",
        csrf_header: str = "",
    ) -> None:
        self.path = path
        self.headers = SimpleNamespace(
            get=lambda key, default="": {
                "Authorization": authorization,
                "Cookie": cookie,
                "X-CSRF-Token": csrf_header,
            }.get(key, default)
        )


def test_csrf_valid_accepts_token_in_request_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "secret")
    handler = MockHandler("/api/server/restart?token=secret")
    assert csrf_valid(handler, None) is True


def test_csrf_valid_accepts_matching_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "secret")
    session_id, csrf_token = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert csrf_valid(handler, {"csrf_token": csrf_token}) is True


def test_csrf_valid_rejects_missing_session_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    session_id, _csrf = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert csrf_valid(handler, None) is False


def test_get_csrf_for_handler_returns_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    session_id, csrf_token = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert get_csrf_for_handler(handler) == csrf_token
