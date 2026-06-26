"""Tests for server/auth.py."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from auth import get_access_token, request_authorized


class MockHandler:
    def __init__(self, path: str = "/", authorization: str = "") -> None:
        self.path = path
        self.headers = SimpleNamespace(get=lambda key, default="": authorization if key == "Authorization" else default)


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
