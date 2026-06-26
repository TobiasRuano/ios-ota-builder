"""Admin password hashing and verification (stdlib PBKDF2)."""

from __future__ import annotations

import hashlib
import os
import secrets

DEFAULT_ITERATIONS = 600_000
MAX_PBKDF2_ITERATIONS = 1_000_000
MIN_PASSWORD_LENGTH = 12
HASH_PREFIX = "pbkdf2"
HASH_ALGORITHM = "sha256"
DEFAULT_ADMIN_USERNAME = "admin"


class PasswordValidationError(ValueError):
    pass


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"{HASH_PREFIX}${HASH_ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, algo, iter_str, salt, expected_hex = stored.split("$", 4)
        if prefix != HASH_PREFIX or algo != HASH_ALGORITHM:
            return False
        iterations = int(iter_str)
        if iterations < 1 or iterations > MAX_PBKDF2_ITERATIONS:
            return False
        expected = bytes.fromhex(expected_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        algo,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return secrets.compare_digest(actual, expected)


def get_admin_username() -> str:
    return os.environ.get("OTA_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME).strip() or DEFAULT_ADMIN_USERNAME


def get_admin_password_hash() -> str:
    raw = os.environ.get("OTA_ADMIN_PASSWORD_HASH", "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    return raw


def admin_login_enabled() -> bool:
    return bool(get_admin_password_hash())


def verify_admin_credentials(username: str, password: str) -> bool:
    if not admin_login_enabled():
        return False
    stored = get_admin_password_hash()
    valid_user = secrets.compare_digest(username, get_admin_username())
    password_ok = verify_password(password, stored)
    return valid_user and password_ok
