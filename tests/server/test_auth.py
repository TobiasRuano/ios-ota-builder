"""Tests for server/auth.py."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from auth import (
    dashboard_auth_mode,
    get_access_token,
    is_session_authenticated,
    is_token_provided_in_request,
    request_authorized,
    safe_next_path,
    wants_html_login_redirect,
)
from credentials import hash_password
from session import create_session


class MockHandler:
    def __init__(
        self,
        path: str = "/",
        *,
        authorization: str = "",
        cookie: str = "",
        command: str = "GET",
        accept: str = "text/html",
    ) -> None:
        self.path = path
        self.command = command
        self.headers = SimpleNamespace(
            get=lambda key, default="": {
                "Authorization": authorization,
                "Cookie": cookie,
                "Accept": accept,
            }.get(key, default)
        )


def test_get_access_token_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "  secret-token  ")
    assert get_access_token() == "secret-token"


def test_get_access_token_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTA_ACCESS_TOKEN", raising=False)
    assert get_access_token() == ""


def test_request_authorized_allows_all_when_token_empty() -> None:
    handler = MockHandler("/my-app/install.html")
    assert request_authorized(handler, "") is True


def test_request_authorized_accepts_query_token() -> None:
    handler = MockHandler("/?token=abc123")
    assert request_authorized(handler, "abc123") is True


def test_request_authorized_accepts_bearer_header() -> None:
    handler = MockHandler("/", authorization="Bearer abc123")
    assert request_authorized(handler, "abc123") is True


def test_request_authorized_rejects_wrong_token() -> None:
    handler = MockHandler("/?token=wrong", authorization="Bearer also-wrong")
    assert request_authorized(handler, "abc123") is False


def test_request_authorized_accepts_valid_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    session_id, _csrf = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert request_authorized(handler, "required-token") is True


def test_is_session_authenticated_requires_valid_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    session_id, _csrf = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert is_session_authenticated(handler) is True


def test_dashboard_auth_mode_prefers_session_without_token_in_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "secret")
    session_id, _csrf = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert dashboard_auth_mode(handler) == "session"


def test_dashboard_auth_mode_uses_token_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)
    monkeypatch.setenv("OTA_ACCESS_TOKEN", "secret")
    session_id, _csrf = create_session()
    handler = MockHandler("/?token=secret", cookie=f"OTA_SESSION={session_id}")
    assert dashboard_auth_mode(handler) == "token"
    assert is_token_provided_in_request(handler, "secret") is True


def test_safe_next_path_blocks_open_redirects() -> None:
    assert safe_next_path("/dashboard") == "/dashboard"
    assert safe_next_path("//evil.example") == "/"
    assert safe_next_path(None) == "/"


def test_wants_html_login_redirect_for_get_html() -> None:
    handler = MockHandler("/", command="GET", accept="text/html")
    assert wants_html_login_redirect(handler) is True
    handler = MockHandler("/", command="POST", accept="text/html")
    assert wants_html_login_redirect(handler) is False


def test_safe_next_path_rejects_backslash() -> None:
    assert safe_next_path("/\\evil") == "/"
    assert safe_next_path("/%5cevil") == "/"


def test_safe_next_path_rejects_api_routes() -> None:
    assert safe_next_path("/api/login") == "/"
    assert safe_next_path("/api/builds/delete") == "/"
    assert safe_next_path("/api/builds/delete?token=x") == "/"
