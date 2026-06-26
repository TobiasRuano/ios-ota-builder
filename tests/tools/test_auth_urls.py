"""Tests for tools/auth_urls.py."""

from __future__ import annotations

from auth_urls import with_access_token


def test_with_access_token_noop_when_token_missing() -> None:
    url = "https://ota.example.com/my-app/install.html"
    assert with_access_token(url, None) == url
    assert with_access_token(url, "") == url


def test_with_access_token_appends_query_param() -> None:
    url = "https://ota.example.com/my-app/install.html"
    result = with_access_token(url, "secret")
    assert result == "https://ota.example.com/my-app/install.html?token=secret"


def test_with_access_token_merges_existing_query() -> None:
    url = "https://ota.example.com/my-app/install.html?foo=bar"
    result = with_access_token(url, "secret")
    assert "foo=bar" in result
    assert "token=secret" in result


def test_with_access_token_overwrites_existing_token() -> None:
    url = "https://ota.example.com/?token=old"
    result = with_access_token(url, "new")
    assert "token=new" in result
    assert "token=old" not in result
