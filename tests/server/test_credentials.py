"""Tests for server/credentials.py."""

from __future__ import annotations

import pytest

from credentials import (
    MAX_PBKDF2_ITERATIONS,
    PasswordValidationError,
    admin_login_enabled,
    get_admin_password_hash,
    hash_password,
    validate_password_strength,
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


def test_verify_password_rejects_excessive_iterations() -> None:
    malicious = f"pbkdf2$sha256$999999999$deadbeef$" + ("00" * 32)
    assert verify_password("anything", malicious) is False


def test_validate_password_strength_requires_min_length() -> None:
    with pytest.raises(PasswordValidationError):
        validate_password_strength("short")
    validate_password_strength("a" * 12)


def test_verify_admin_credentials_runs_pbkdf2_for_wrong_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = hash_password("admin-secret")
    monkeypatch.setenv("OTA_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("OTA_ADMIN_PASSWORD_HASH", stored)

    assert verify_admin_credentials("wrong-user", "admin-secret") is False
    assert MAX_PBKDF2_ITERATIONS == 1_000_000
