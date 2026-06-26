"""Tests for server/session.py."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import session as session_module
from session import (
    SESSION_COOKIE_NAME,
    SessionCapacityError,
    clear_all_sessions,
    clear_session_cookie_header,
    create_session,
    destroy_session,
    get_csrf_token,
    get_session_id_from_handler,
    max_active_sessions,
    parse_cookies,
    session_cookie_header,
    validate_csrf_token,
    validate_session,
)


@pytest.fixture(autouse=True)
def clear_sessions() -> None:
    with session_module._lock:
        session_module._sessions.clear()
    yield
    with session_module._lock:
        session_module._sessions.clear()


def test_create_and_validate_session() -> None:
    session_id, csrf_token = create_session()
    assert csrf_token
    assert validate_session(session_id) is True
    assert validate_csrf_token(session_id, csrf_token) is True
    destroy_session(session_id)
    assert validate_session(session_id) is False


def test_parse_cookies_and_handler_lookup() -> None:
    cookies = parse_cookies("foo=bar; OTA_SESSION=abc123; baz=qux")
    assert cookies[SESSION_COOKIE_NAME] == "abc123"

    handler = SimpleNamespace(
        headers=SimpleNamespace(
            get=lambda key, default="": "foo=bar; OTA_SESSION=abc123; baz=qux"
            if key == "Cookie"
            else default
        )
    )
    assert get_session_id_from_handler(handler) == "abc123"


def test_session_cookie_headers() -> None:
    assert "HttpOnly" in session_cookie_header("sid")
    assert "Secure" in session_cookie_header("sid")
    assert "Max-Age=0" in clear_session_cookie_header()


def test_expired_session_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTA_SESSION_MAX_AGE", "1")
    session_id, csrf_token = create_session()
    with session_module._lock:
        session_module._sessions[session_id] = (time.time() - 1, csrf_token)
    assert validate_session(session_id) is False
    assert get_csrf_token(session_id) is None


def test_clear_all_sessions() -> None:
    session_id, _csrf = create_session()
    assert validate_session(session_id) is True
    clear_all_sessions()
    assert validate_session(session_id) is False


def test_validate_csrf_rejects_wrong_token() -> None:
    session_id, csrf_token = create_session()
    assert validate_csrf_token(session_id, "wrong") is False
    assert validate_csrf_token(session_id, csrf_token) is True


def test_create_session_rejects_when_at_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTA_MAX_ACTIVE_SESSIONS", "2")
    create_session()
    create_session()
    with pytest.raises(SessionCapacityError):
        create_session()
    assert max_active_sessions() == 2
