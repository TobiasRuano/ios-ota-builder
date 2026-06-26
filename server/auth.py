"""OTA server access control."""

from __future__ import annotations

import os
import sys
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from credentials import admin_login_enabled  # noqa: E402
from session import get_session_id_from_handler, validate_session  # noqa: E402
from ui_theme import unauthorized_html  # noqa: E402


def get_access_token() -> str:
    return os.environ.get("OTA_ACCESS_TOKEN", "").strip()


def _token_authorized(handler: SimpleHTTPRequestHandler, token: str) -> bool:
    if not token:
        return True

    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    if query.get("token", [""])[0] == token:
        return True

    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {token}":
        return True

    return False


def _session_authorized(handler: SimpleHTTPRequestHandler) -> bool:
    if not admin_login_enabled():
        return False
    session_id = get_session_id_from_handler(handler)
    return validate_session(session_id)


def request_authorized(handler: SimpleHTTPRequestHandler, token: str) -> bool:
    if _token_authorized(handler, token):
        return True
    if _session_authorized(handler):
        return True
    return False


def wants_html_login_redirect(handler: SimpleHTTPRequestHandler) -> bool:
    if handler.command != "GET":
        return False
    accept = handler.headers.get("Accept", "")
    if "text/html" in accept or "*/*" in accept or accept == "":
        return True
    path = urlparse(handler.path).path.rstrip("/") or "/"
    return path in ("/", "/index.html", "/login")


def safe_next_path(raw: str | None) -> str:
    if not raw:
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def send_login_redirect(handler: SimpleHTTPRequestHandler, *, next_path: str | None = None) -> None:
    parsed = urlparse(handler.path)
    target = next_path or (parsed.path + (f"?{parsed.query}" if parsed.query else ""))
    location = f"/login?next={quote(safe_next_path(target), safe='')}"
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.end_headers()


def send_unauthorized(handler: SimpleHTTPRequestHandler) -> None:
    if admin_login_enabled() and wants_html_login_redirect(handler):
        send_login_redirect(handler)
        return

    body = unauthorized_html().encode("utf-8")
    handler.send_response(401)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("WWW-Authenticate", 'Bearer realm="OTA Builds"')
    handler.end_headers()
    handler.wfile.write(body)
