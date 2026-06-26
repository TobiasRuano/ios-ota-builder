"""CSRF validation for session-authenticated POST requests."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from auth import get_access_token, is_token_provided_in_request
from session import get_csrf_token, get_session_id_from_handler, validate_csrf_token


def csrf_token_from_request(
    handler: BaseHTTPRequestHandler,
    form: dict[str, str] | None = None,
) -> str | None:
    if form and form.get("csrf_token"):
        return form["csrf_token"]
    header = handler.headers.get("X-CSRF-Token", "").strip()
    return header or None


def csrf_valid(handler: BaseHTTPRequestHandler, form: dict[str, str] | None = None) -> bool:
    """Allow token-authenticated clients; require CSRF for session-only auth."""
    token = get_access_token()
    if token and is_token_provided_in_request(handler, token):
        return True
    session_id = get_session_id_from_handler(handler)
    submitted = csrf_token_from_request(handler, form)
    return validate_csrf_token(session_id, submitted)


def get_csrf_for_handler(handler: BaseHTTPRequestHandler) -> str | None:
    session_id = get_session_id_from_handler(handler)
    return get_csrf_token(session_id)
