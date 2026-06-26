"""In-memory session store for admin login."""

from __future__ import annotations

import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler

SESSION_COOKIE_NAME = "OTA_SESSION"
DEFAULT_MAX_AGE = 7 * 24 * 3600

_lock = threading.Lock()
_sessions: dict[str, float] = {}


def session_max_age() -> int:
    raw = os.environ.get("OTA_SESSION_MAX_AGE", str(DEFAULT_MAX_AGE))
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_MAX_AGE


def create_session() -> str:
    session_id = secrets.token_urlsafe(32)
    expires = time.time() + session_max_age()
    with _lock:
        _sessions[session_id] = expires
        _purge_expired_locked()
    return session_id


def validate_session(session_id: str | None) -> bool:
    if not session_id:
        return False
    now = time.time()
    with _lock:
        expires = _sessions.get(session_id)
        if expires is None:
            return False
        if now >= expires:
            del _sessions[session_id]
            return False
        return True


def destroy_session(session_id: str | None) -> None:
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)


def _purge_expired_locked() -> None:
    now = time.time()
    for session_id, expires in list(_sessions.items()):
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
