"""Tests for server/auth.py."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from auth import (
    get_access_token,
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
    session_id = create_session()
    handler = MockHandler("/", cookie=f"OTA_SESSION={session_id}")
    assert request_authorized(handler, "required-token") is True


def test_safe_next_path_blocks_open_redirects() -> None:
    assert safe_next_path("/dashboard") == "/dashboard"
    assert safe_next_path("//evil.example") == "/"
    assert safe_next_path(None) == "/"


def test_wants_html_login_redirect_for_get_html() -> None:
    handler = MockHandler("/", command="GET", accept="text/html")
    assert wants_html_login_redirect(handler) is True
    handler = MockHandler("/", command="POST", accept="text/html")
    assert wants_html_login_redirect(handler) is False
