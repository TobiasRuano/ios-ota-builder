#!/usr/bin/env python3
"""Minimal static file server with OTA MIME types, token auth, and dynamic index."""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tools"))

from auth import get_access_token, request_authorized, send_unauthorized  # noqa: E402
from build_delete import BuildDeleteError, delete_build  # noqa: E402
from ota_index import collect_builds, load_projects_config, render_index  # noqa: E402
from auth_urls import with_access_token  # noqa: E402


class OTAHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **getattr(SimpleHTTPRequestHandler, "extensions_map", {}),
        ".ipa": "application/octet-stream",
        ".plist": "application/xml",
        ".json": "application/json",
        ".log": "text/plain",
        ".md": "text/plain",
    }

    def _route_path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def _check_auth(self) -> bool:
        token = get_access_token()
        if request_authorized(self, token):
            return True
        send_unauthorized(self)
        return False

    def _ota_dir(self) -> Path:
        return Path(os.environ["OTA_BUILDS_DIR"]).resolve()

    def _projects_json(self) -> Path:
        return Path(os.environ.get("OTA_PROJECTS_JSON", ROOT / "config/projects.json"))

    def _base_url(self) -> str:
        return os.environ.get("OTA_BASE_URL", "").rstrip("/")

    def _index_data(self) -> dict:
        projects = load_projects_config(self._projects_json())
        return collect_builds(self._ota_dir(), projects)

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _effective_token(self) -> str | None:
        server_token = get_access_token()
        if server_token:
            return server_token
        parsed = urlparse(self.path)
        return parse_qs(parsed.query).get("token", [""])[0] or None

    def _serve_dynamic_index(self) -> None:
        data = self._index_data()
        token = self._effective_token()
        html_body = render_index(
            data,
            self._base_url(),
            token,
            enable_delete=bool(token),
        )
        self._send_bytes(200, html_body.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_dynamic_builds_json(self) -> None:
        data = self._index_data()
        body = json.dumps(data, indent=2).encode("utf-8") + b"\n"
        self._send_bytes(200, body, "application/json; charset=utf-8")

    def _parse_form_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        parsed = parse_qs(raw.decode("utf-8", errors="replace"))
        return {k: v[0] if v else "" for k, v in parsed.items()}

    def _handle_delete(self) -> None:
        form = self._parse_form_body()
        project_id = form.get("project_id", "").strip()
        build_dir = form.get("build_dir", "").strip()
        token = get_access_token()
        projects = load_projects_config(self._projects_json())
        allowed = set(projects.keys()) if projects else None

        try:
            removed = delete_build(
                self._ota_dir(),
                project_id,
                build_dir,
                allowed_projects=allowed,
            )
            print(f"deleted build: {removed}", flush=True)
        except BuildDeleteError as exc:
            body = f"Delete failed: {exc}".encode("utf-8")
            self._send_bytes(400, body, "text/plain; charset=utf-8")
            return

        redirect = with_access_token("/", token) if token else "/"
        self.send_response(302)
        self.send_header("Location", redirect)
        self.end_headers()

    def do_GET(self) -> None:
        if not self._check_auth():
            return
        path = self._route_path()
        if path in ("/", "/index.html"):
            self._serve_dynamic_index()
            return
        if path == "/builds.json":
            self._serve_dynamic_builds_json()
            return
        return super().do_GET()

    def do_HEAD(self) -> None:
        if not self._check_auth():
            return
        path = self._route_path()
        if path in ("/", "/index.html", "/builds.json"):
            self.send_response(200)
            self.end_headers()
            return
        return super().do_HEAD()

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        if self._route_path() == "/api/builds/delete":
            self._handle_delete()
            return
        self.send_error(404)


def main() -> None:
    root = Path(os.environ["OTA_BUILDS_DIR"]).resolve()
    port = int(os.environ.get("OTA_PORT", "8765"))
    token = get_access_token()
    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), OTAHandler)
    if token:
        print(f"Serving {root} at http://127.0.0.1:{port}/ (auth: token required, dynamic index)")
    else:
        print(f"Serving {root} at http://127.0.0.1:{port}/ (auth: disabled)")
    server.serve_forever()


if __name__ == "__main__":
    main()
