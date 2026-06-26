"""OTA server access control."""

from __future__ import annotations

import os
import sys
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from ui_theme import unauthorized_html  # noqa: E402


def get_access_token() -> str:
    return os.environ.get("OTA_ACCESS_TOKEN", "").strip()


def request_authorized(handler: SimpleHTTPRequestHandler, token: str) -> bool:
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


def send_unauthorized(handler: SimpleHTTPRequestHandler) -> None:
    body = unauthorized_html().encode("utf-8")
    handler.send_response(401)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("WWW-Authenticate", 'Bearer realm="OTA Builds"')
    handler.end_headers()
    handler.wfile.write(body)
