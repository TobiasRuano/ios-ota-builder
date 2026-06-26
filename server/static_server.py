#!/usr/bin/env python3
"""Minimal static file server with OTA MIME types and token auth."""

from __future__ import annotations

import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_access_token, request_authorized, send_unauthorized  # noqa: E402


class OTAHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **getattr(SimpleHTTPRequestHandler, "extensions_map", {}),
        ".ipa": "application/octet-stream",
        ".plist": "application/xml",
        ".json": "application/json",
        ".log": "text/plain",
        ".md": "text/plain",
    }

    def _check_auth(self) -> bool:
        token = get_access_token()
        if request_authorized(self, token):
            return True
        send_unauthorized(self)
        return False

    def do_GET(self) -> None:
        if not self._check_auth():
            return
        return super().do_GET()

    def do_HEAD(self) -> None:
        if not self._check_auth():
            return
        return super().do_HEAD()


def main() -> None:
    root = Path(os.environ["OTA_BUILDS_DIR"]).resolve()
    port = int(os.environ.get("OTA_PORT", "8765"))
    token = get_access_token()
    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), OTAHandler)
    if token:
        print(f"Serving {root} at http://127.0.0.1:{port}/ (auth: token required)")
    else:
        print(f"Serving {root} at http://127.0.0.1:{port}/ (auth: disabled)")
    server.serve_forever()


if __name__ == "__main__":
    main()
