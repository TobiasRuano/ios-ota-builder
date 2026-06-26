"""Tests for server/credentials.py."""

from __future__ import annotations

import pytest

from credentials import (
    admin_login_enabled,
    get_admin_password_hash,
    hash_password,
    verify_admin_credentials,
    verify_password,
)


def test_hash_and_verify_password_roundtrip() -> None:
    stored = hash_password("secret-pass")
    assert stored.startswith("pbkdf2$sha256$")
    assert verify_password("secret-pass", stored) is True
    assert verify_password("wrong-pass", stored) is False


def test_get_admin_password_hash_strips_single_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = hash_password("secret-pass")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", f"'{stored}'")
    assert get_admin_password_hash() == stored


def test_admin_login_enabled_requires_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTA_ADMIN_PASSWORD_HASH", raising=False)
    assert admin_login_enabled() is False

    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", hash_password("x"))
    assert admin_login_enabled() is True


def test_verify_admin_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = hash_password("admin-secret")
    monkeypatch.setenv("OTA_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)

    assert verify_admin_credentials("admin", "admin-secret") is True
    assert verify_admin_credentials("admin", "nope") is False
    assert verify_admin_credentials("other", "admin-secret") is False
