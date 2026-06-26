#!/usr/bin/env python3
"""Minimal static file server with OTA MIME types, token auth, and dynamic index."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tools"))

from auth import (  # noqa: E402
    dashboard_auth_mode,
    get_access_token,
    is_session_authenticated,
    is_token_provided_in_request,
    request_authorized,
    safe_next_path,
    send_unauthorized,
)
from build_delete import BuildDeleteError, delete_build  # noqa: E402
from build_jobs import (  # noqa: E402
    BuildJobError,
    active_job_for_project,
    create_job,
    is_build_locked,
    list_jobs,
    log_path as job_log_path,
    read_job,
    schedule_job,
)
from client_ip import client_ip_from_request  # noqa: E402
from credentials import admin_login_enabled, verify_admin_credentials  # noqa: E402
from csrf import csrf_valid, get_csrf_for_handler  # noqa: E402
from git_api import (  # noqa: E402
    GitApiError,
    check_secrets_sync,
    get_git_config,
    get_project_repo_path,
    git_fetch,
    git_status,
    list_branches,
)
from login_rate_limit import is_rate_limited, record_failure  # noqa: E402
from ota_dynamic import parse_ota_artifact_path, render_ota_artifact  # noqa: E402
from server_restart import schedule_restart  # noqa: E402
from ota_index import (  # noqa: E402
    collect_builds,
    collect_disk_stats,
    find_latest_build,
    load_projects_config,
    render_index,
)
from auth_urls import with_access_token  # noqa: E402
from session import (  # noqa: E402
    SessionCapacityError,
    clear_session_cookie_header,
    create_session,
    destroy_session,
    get_session_id_from_handler,
    session_cookie_header,
)
from ui_theme import login_html  # noqa: E402

SERVER_START_MONO: float = 0.0
MAX_FORM_BODY_BYTES = 8192
_RAW_BODY_UNSET = object()


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

    @staticmethod
    def _is_public_path(path: str, *, method: str) -> bool:
        if path == "/health":
            return True
        if path == "/login" and method in ("GET", "HEAD"):
            return True
        if path == "/api/login" and method in ("GET", "HEAD", "POST"):
            return True
        return False

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

    def _ota_token(self) -> str | None:
        """Server access token for OTA artifact rendering (always required for iOS installs)."""
        return get_access_token() or None

    def _redirect_token(self) -> str | None:
        """Token to append to browser redirects; omitted for session-authenticated users."""
        if dashboard_auth_mode(self) == "session":
            return None
        return self._ota_token()

    def _effective_token(self) -> str | None:
        return self._ota_token()

    def _serve_health(self, *, head: bool = False) -> None:
        ota_dir = self._ota_dir()
        payload = {
            "ok": True,
            "uptime_seconds": int(time.monotonic() - SERVER_START_MONO),
            "ota_builds_dir_writable": os.access(ota_dir, os.W_OK),
        }
        if head:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(200, body, "application/json; charset=utf-8")

    def _authorized_redirect(self, path: str) -> str:
        token = self._redirect_token()
        return with_access_token(path, token) if token else path

    def _serve_api_login_redirect(self) -> None:
        if request_authorized(self, get_access_token()):
            location = self._authorized_redirect("/")
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()
            return
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()

    def _serve_login(self) -> None:
        if not admin_login_enabled():
            self.send_error(404, "Admin login is not configured")
            return
        query = parse_qs(urlparse(self.path).query)
        next_path = safe_next_path(query.get("next", ["/"])[0])
        if request_authorized(self, get_access_token()):
            location = self._authorized_redirect(next_path)
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()
            return
        body = login_html(next_path=next_path).encode("utf-8")
        self._send_bytes(200, body, "text/html; charset=utf-8")

    def _handle_login(self) -> None:
        if not admin_login_enabled():
            self.send_error(404, "Admin login is not configured")
            return

        client_ip = client_ip_from_request(self)
        if is_rate_limited(client_ip):
            body = login_html(
                next_path="/",
                error="Too many failed attempts. Try again in a few minutes.",
            ).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        form = self._read_limited_form_body()
        if form is None:
            return

        username = form.get("username", "").strip()
        password = form.get("password", "")
        next_path = safe_next_path(form.get("next", "/"))

        if not verify_admin_credentials(username, password):
            record_failure(client_ip)
            body = login_html(next_path=next_path, error="Invalid username or password.").encode(
                "utf-8"
            )
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        try:
            session_id, _csrf_token = create_session()
        except SessionCapacityError:
            body = login_html(
                next_path=next_path,
                error="Too many active sessions. Try again later or restart the server.",
            ).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        redirect = next_path
        self.send_response(302)
        self.send_header("Location", redirect)
        self.send_header("Set-Cookie", session_cookie_header(session_id))
        self.end_headers()

    def _handle_logout(self) -> None:
        destroy_session(get_session_id_from_handler(self))
        redirect = "/login"
        self.send_response(302)
        self.send_header("Location", redirect)
        self.send_header("Set-Cookie", clear_session_cookie_header())
        self.end_headers()

    def _parse_latest_project(self, path: str) -> str | None:
        prefix = "/latest/"
        if not path.startswith(prefix):
            return None
        project_id = path[len(prefix) :]
        if not project_id or "/" in project_id:
            return None
        return project_id

    def _serve_latest_redirect(self, project_id: str, *, head: bool = False) -> None:
        projects = load_projects_config(self._projects_json())
        if project_id not in projects:
            self.send_error(404, f"Unknown project: {project_id}")
            return

        latest = find_latest_build(
            self._ota_dir(),
            project_id,
            projects_config=projects,
        )
        if latest is None:
            self.send_error(404, f"No successful builds for project: {project_id}")
            return

        base = self._base_url()
        rel_install = f"/{latest['path']}/install.html"
        target = f"{base}{rel_install}" if base else rel_install
        location = with_access_token(target, self._redirect_token())
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _min_disk_mb(self) -> int:
        raw = os.environ.get("OTA_STATUS_MIN_DISK_MB", "5000")
        try:
            return max(0, int(raw))
        except ValueError:
            return 5000

    def _probe_tunnel(self, base_url: str) -> dict:
        health_url = f"{base_url.rstrip('/')}/health"
        reachable = False
        try:
            req = urllib.request.Request(health_url, method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as resp:
                reachable = 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            reachable = False
        return {"reachable": reachable, "url": health_url}

    def _server_status(self) -> dict:
        ota_dir = self._ota_dir()
        min_disk_mb = self._min_disk_mb()
        status: dict = {
            "disk": collect_disk_stats(ota_dir, min_disk_mb=min_disk_mb),
            "uptime_seconds": int(time.monotonic() - SERVER_START_MONO),
            "ota_builds_dir_writable": os.access(ota_dir, os.W_OK),
        }
        base_url = self._base_url()
        probe_tunnel = os.environ.get("OTA_STATUS_PROBE_TUNNEL", "0") == "1"
        if probe_tunnel and base_url:
            status["tunnel"] = self._probe_tunnel(base_url)
        return status

    def _serve_dynamic_index(self) -> None:
        data = self._index_data()
        mode = dashboard_auth_mode(self)
        token = get_access_token() if mode == "token" else None
        csrf_token = get_csrf_for_handler(self) if mode == "session" else None
        authenticated = mode in ("session", "token")
        html_body = render_index(
            data,
            self._base_url(),
            access_token=token,
            auth_mode=mode,
            csrf_token=csrf_token,
            enable_delete=authenticated,
            enable_restart=authenticated,
            enable_logout=admin_login_enabled(),
            enable_build=authenticated,
            server_status=self._server_status(),
        )
        self._send_bytes(200, html_body.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_dynamic_builds_json(self) -> None:
        data = self._index_data()
        body = json.dumps(data, indent=2).encode("utf-8") + b"\n"
        self._send_bytes(200, body, "application/json; charset=utf-8")

    def _serve_dynamic_ota_artifact(self, path: str) -> bool:
        parsed = parse_ota_artifact_path(path)
        if parsed is None:
            return False
        project_id, build_dir_name, artifact = parsed
        rendered = render_ota_artifact(
            ota_dir=self._ota_dir(),
            projects_json=self._projects_json(),
            base_url=self._base_url(),
            token=self._effective_token(),
            project_id=project_id,
            build_dir_name=build_dir_name,
            artifact=artifact,
        )
        if rendered is None:
            self.send_error(404, "Build artifact not found")
            return True
        body, content_type = rendered
        self._send_bytes(200, body, content_type)
        return True

    def _read_limited_raw_body(self) -> bytes | None:
        cached = getattr(self, "_cached_raw_body", _RAW_BODY_UNSET)
        if cached is not _RAW_BODY_UNSET:
            return cached

        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            self._cached_raw_body = None
            return None
        if length < 0:
            self.send_error(400, "Invalid Content-Length")
            self._cached_raw_body = None
            return None
        if length > MAX_FORM_BODY_BYTES:
            self.send_error(413, "Request body too large")
            self._cached_raw_body = None
            return None
        raw = self.rfile.read(length) if length else b""
        self._cached_raw_body = raw
        return raw

    def _read_limited_form_body(self) -> dict[str, str] | None:
        raw = self._read_limited_raw_body()
        if raw is None:
            return None
        parsed = parse_qs(raw.decode("utf-8", errors="replace"))
        return {k: v[0] if v else "" for k, v in parsed.items()}

    def _parse_json_body(self) -> dict:
        raw = self._read_limited_raw_body()
        if raw is None or not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _projects(self) -> dict:
        return load_projects_config(self._projects_json())

    def _handle_git_status(self) -> None:
        parsed = urlparse(self.path)
        project_id = parse_qs(parsed.query).get("project", [""])[0].strip()
        try:
            repo_path = get_project_repo_path(self._projects_json(), project_id)
            git_cfg = get_git_config(self._projects_json(), project_id)
            status = git_status(repo_path)
            status["project_id"] = project_id
            status["build_locked"] = is_build_locked(self._ota_dir(), project_id)
            active = active_job_for_project(ROOT, project_id)
            status["active_job"] = active
            status["secrets"] = check_secrets_sync(repo_path, git_cfg["secrets_sync"])
            self._send_json(200, status)
        except (GitApiError, BuildJobError) as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_git_branches(self) -> None:
        parsed = urlparse(self.path)
        project_id = parse_qs(parsed.query).get("project", [""])[0].strip()
        try:
            repo_path = get_project_repo_path(self._projects_json(), project_id)
            git_cfg = get_git_config(self._projects_json(), project_id)
            branches = list_branches(repo_path, remote=git_cfg["remote"])
            branches["project_id"] = project_id
            self._send_json(200, branches)
        except GitApiError as exc:
            self._send_json(400, {"error": str(exc)})

    def _reject_csrf(self) -> None:
        self._send_bytes(403, b"Invalid or missing CSRF token", "text/plain; charset=utf-8")

    def _handle_git_fetch(self) -> None:
        form = self._parse_form_body()
        if not form:
            form = self._parse_json_body()
        if not csrf_valid(self, form):
            self._reject_csrf()
            return
        project_id = str(form.get("project_id", "")).strip()
        try:
            repo_path = get_project_repo_path(self._projects_json(), project_id)
            git_cfg = get_git_config(self._projects_json(), project_id)
            result = git_fetch(repo_path, remote=git_cfg["remote"])
            result["project_id"] = project_id
            self._send_json(200, result)
        except GitApiError as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_build_trigger(self) -> None:
        form = self._parse_form_body()
        if not form:
            form = self._parse_json_body()
        if not csrf_valid(self, form):
            self._reject_csrf()
            return
        project_id = str(form.get("project_id", "")).strip()
        branch = str(form.get("branch", "")).strip()
        git_mode = str(form.get("git_mode", "auto")).strip() or "auto"
        configuration = str(form.get("configuration", "")).strip()
        projects = self._projects()
        allowed = set(projects.keys()) if projects else None

        try:
            if active_job_for_project(ROOT, project_id):
                raise BuildJobError("a build job is already active for this project")
            job = create_job(
                ROOT,
                project_id=project_id,
                branch=branch,
                git_mode=git_mode,
                configuration=configuration,
                allowed_projects=allowed,
            )
            schedule_job(ROOT, job["id"])
            print(f"scheduled build job: {job['id']}", flush=True)
            self._send_json(202, job)
        except (BuildJobError, FileNotFoundError) as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_build_job_get(self, job_id: str) -> None:
        job = read_job(ROOT, job_id)
        if job is None:
            self._send_json(404, {"error": "job not found"})
            return
        self._send_json(200, job)

    def _handle_build_jobs_list(self) -> None:
        parsed = urlparse(self.path)
        project_id = parse_qs(parsed.query).get("project", [""])[0].strip()
        jobs = list_jobs(ROOT, project_id=project_id, limit=20)
        self._send_json(200, {"jobs": jobs})

    def _handle_build_job_log(self, job_id: str) -> None:
        job = read_job(ROOT, job_id)
        if job is None:
            self._send_json(404, {"error": "job not found"})
            return
        log_file = job_log_path(ROOT, job_id)
        if not log_file.is_file():
            self._send_bytes(200, b"", "text/plain; charset=utf-8")
            return
        content = log_file.read_text(encoding="utf-8", errors="replace")
        tail = content[-50000:] if len(content) > 50000 else content
        self._send_bytes(200, tail.encode("utf-8"), "text/plain; charset=utf-8")

    def _parse_job_id(self, path: str) -> tuple[str | None, str | None]:
        prefix = "/api/builds/jobs/"
        if not path.startswith(prefix):
            return None, None
        rest = path[len(prefix) :]
        if not rest:
            return "", None
        if rest.endswith("/log"):
            return rest[: -len("/log")], "log"
        return rest, "job"

    def _parse_form_body(self) -> dict[str, str]:
        form = self._read_limited_form_body()
        return form if form is not None else {}

    def _handle_delete(self) -> None:
        form = self._read_limited_form_body()
        if form is None:
            return
        if not csrf_valid(self, form):
            self._reject_csrf()
            return
        project_id = form.get("project_id", "").strip()
        build_dir = form.get("build_dir", "").strip()
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

        redirect = self._authorized_redirect("/")
        self.send_response(302)
        self.send_header("Location", redirect)
        self.end_headers()

    def _handle_restart(self) -> None:
        form = self._parse_form_body()
        if form and not csrf_valid(self, form):
            self._reject_csrf()
            return
        if not form and not csrf_valid(self, None):
            self._reject_csrf()
            return
        try:
            schedule_restart(root=ROOT)
        except FileNotFoundError as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self._send_bytes(500, body, "application/json; charset=utf-8")
            return

        print("scheduled server restart", flush=True)
        body = json.dumps(
            {"restarting": True, "message": "Server restart scheduled"}
        ).encode("utf-8")
        self._send_bytes(202, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self._route_path()
        if self._is_public_path(path, method="GET"):
            if path == "/health":
                self._serve_health()
            elif path == "/api/login":
                self._serve_api_login_redirect()
            elif path == "/login":
                self._serve_login()
            return
        if not self._check_auth():
            return
        if path in ("/", "/index.html"):
            self._serve_dynamic_index()
            return
        if path == "/builds.json":
            self._serve_dynamic_builds_json()
            return
        if path == "/api/git/status":
            self._handle_git_status()
            return
        if path == "/api/git/branches":
            self._handle_git_branches()
            return
        if path == "/api/builds/jobs":
            self._handle_build_jobs_list()
            return
        job_id, job_kind = self._parse_job_id(path)
        if job_id is not None:
            if job_kind == "log" and job_id:
                self._handle_build_job_log(job_id)
                return
            if job_kind == "job" and job_id:
                self._handle_build_job_get(job_id)
                return
        latest_project = self._parse_latest_project(path)
        if latest_project is not None:
            self._serve_latest_redirect(latest_project)
            return
        if self._serve_dynamic_ota_artifact(path):
            return
        return super().do_GET()

    def do_HEAD(self) -> None:
        path = self._route_path()
        if self._is_public_path(path, method="HEAD"):
            if path == "/health":
                self._serve_health(head=True)
            elif path == "/api/login":
                self.send_response(302)
                self.end_headers()
            elif path == "/login":
                self.send_response(200)
                self.end_headers()
            return
        if not self._check_auth():
            return
        if path in ("/", "/index.html", "/builds.json"):
            self.send_response(200)
            self.end_headers()
            return
        latest_project = self._parse_latest_project(path)
        if latest_project is not None:
            self._serve_latest_redirect(latest_project, head=True)
            return
        if parse_ota_artifact_path(path) is not None:
            self.send_response(200)
            self.end_headers()
            return
        return super().do_HEAD()

    def do_POST(self) -> None:
        path = self._route_path()
        if path == "/api/login":
            self._handle_login()
            return
        if path == "/api/logout":
            self._handle_logout()
            return
        if not self._check_auth():
            return
        if path == "/api/builds/delete":
            self._handle_delete()
            return
        if path == "/api/server/restart":
            self._handle_restart()
            return
        if path == "/api/git/fetch":
            self._handle_git_fetch()
            return
        if path == "/api/builds/trigger":
            self._handle_build_trigger()
            return
        self.send_error(404)


def main() -> None:
    global SERVER_START_MONO
    SERVER_START_MONO = time.monotonic()
    root = Path(os.environ["OTA_BUILDS_DIR"]).resolve()
    port = int(os.environ.get("OTA_PORT", "8765"))
    token = get_access_token()
    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), OTAHandler)
    auth_bits = []
    if token:
        auth_bits.append("token")
    if admin_login_enabled():
        auth_bits.append("login")
    if auth_bits:
        print(
            f"Serving {root} at http://127.0.0.1:{port}/ "
            f"(auth: {', '.join(auth_bits)}, dynamic index)"
        )
    else:
        print("Warning: OTA_ACCESS_TOKEN not set — auth disabled", file=sys.stderr)
        print(f"Serving {root} at http://127.0.0.1:{port}/ (auth: disabled)")
    server.serve_forever()


if __name__ == "__main__":
    main()
