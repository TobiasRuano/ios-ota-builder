"""In-memory session store for admin login."""

from __future__ import annotations

import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler

SESSION_COOKIE_NAME = "OTA_SESSION"
DEFAULT_MAX_AGE = 7 * 24 * 3600
DEFAULT_MAX_ACTIVE_SESSIONS = 32

_lock = threading.Lock()
_sessions: dict[str, tuple[float, str]] = {}


class SessionCapacityError(RuntimeError):
    pass


def session_max_age() -> int:
    raw = os.environ.get("OTA_SESSION_MAX_AGE", str(DEFAULT_MAX_AGE))
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_MAX_AGE


def max_active_sessions() -> int:
    raw = os.environ.get("OTA_MAX_ACTIVE_SESSIONS", str(DEFAULT_MAX_ACTIVE_SESSIONS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_ACTIVE_SESSIONS


def create_session() -> tuple[str, str]:
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires = time.time() + session_max_age()
    with _lock:
        _purge_expired_locked()
        if len(_sessions) >= max_active_sessions():
            raise SessionCapacityError("maximum active sessions reached")
        _sessions[session_id] = (expires, csrf_token)
    return session_id, csrf_token


def validate_session(session_id: str | None) -> bool:
    if not session_id:
        return False
    now = time.time()
    with _lock:
        entry = _sessions.get(session_id)
        if entry is None:
            return False
        expires, _csrf = entry
        if now >= expires:
            del _sessions[session_id]
            return False
        return True


def get_csrf_token(session_id: str | None) -> str | None:
    if not session_id:
        return None
    now = time.time()
    with _lock:
        entry = _sessions.get(session_id)
        if entry is None:
            return None
        expires, csrf_token = entry
        if now >= expires:
            del _sessions[session_id]
            return None
        return csrf_token


def validate_csrf_token(session_id: str | None, csrf_token: str | None) -> bool:
    if not session_id or not csrf_token:
        return False
    stored = get_csrf_token(session_id)
    if stored is None:
        return False
    return secrets.compare_digest(stored, csrf_token)


def destroy_session(session_id: str | None) -> None:
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)


def clear_all_sessions() -> None:
    with _lock:
        _sessions.clear()


def _purge_expired_locked() -> None:
    now = time.time()
    for session_id, (expires, _csrf) in list(_sessions.items()):
        if now >= expires:
            del _sessions[session_id]


def parse_cookies(header: str | None) -> dict[str, str]:
    if not header:
        return {}
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def get_session_id_from_handler(handler: BaseHTTPRequestHandler) -> str | None:
    cookies = parse_cookies(handler.headers.get("Cookie"))
    session_id = cookies.get(SESSION_COOKIE_NAME)
    return session_id or None


def session_cookie_header(session_id: str) -> str:
    max_age = session_max_age()
    return (
        f"{SESSION_COOKIE_NAME}={session_id}; "
        f"Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={max_age}"
    )


def clear_session_cookie_header() -> str:
    return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"
