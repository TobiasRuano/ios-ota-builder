"""Build OTA dashboard index from disk artifacts."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from auth_urls import with_access_token
from ui_theme import base_head


def load_summary(build_dir: Path) -> dict | None:
    summary_path = build_dir / "summary.json"
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _build_entry_if_valid(build_dir: Path, project_id: str) -> dict | None:
    if not build_dir.is_dir():
        return None
    if not (build_dir / "app.ipa").is_file():
        return None
    summary = load_summary(build_dir)
    rel = f"{project_id}/{build_dir.name}"
    entry = {
        "dir": build_dir.name,
        "path": rel,
        "project_id": project_id,
        "has_ipa": True,
        "has_install": (build_dir / "install.html").is_file(),
    }
    if summary:
        entry.update(
            {
                "status": summary.get("status"),
                "branch": summary.get("branch"),
                "commit": summary.get("commit"),
                "date": summary.get("date"),
                "version": summary.get("version"),
                "build_number": summary.get("build_number"),
                "install_url": summary.get("install_url"),
                "manifest_url": summary.get("manifest_url"),
                "ipa_url": summary.get("ipa_url"),
            }
        )
    return entry


def find_latest_build(
    ota_dir: Path,
    project_id: str,
    *,
    projects_config: dict | None = None,
) -> dict | None:
    if projects_config is not None and project_id not in projects_config:
        return None

    project_dir = ota_dir / project_id
    if not project_dir.is_dir():
        return None

    for build_dir in sorted(project_dir.iterdir(), reverse=True):
        entry = _build_entry_if_valid(build_dir, project_id)
        if entry is None:
            continue
        if entry.get("status") != "success":
            continue
        return {
            "project_id": project_id,
            "build_dir": entry["dir"],
            "path": entry["path"],
        }
    return None


def collect_builds(ota_dir: Path, projects_config: dict) -> dict:
    result: dict = {
        "projects": {},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    for project_id, meta in projects_config.items():
        project_dir = ota_dir / project_id
        builds: list[dict] = []
        if project_dir.is_dir():
            for build_dir in sorted(project_dir.iterdir(), reverse=True):
                entry = _build_entry_if_valid(build_dir, project_id)
                if entry is not None:
                    builds.append(entry)

        result["projects"][project_id] = {
            "display_name": meta.get("display_name", project_id),
            "builds": builds,
        }

    return result


def _status_badge(status: str | None) -> str:
    if not status:
        return ""
    label = html.escape(str(status))
    return (
        f'<span class="status-badge">'
        f'<span class="status-dot" aria-hidden="true"></span>{label}</span>'
    )


def render_index(
    data: dict,
    base_url: str,
    access_token: str | None = None,
    *,
    enable_delete: bool = True,
) -> str:
    base = base_url.rstrip("/")
    token = access_token or ""

    def u(url: str) -> str:
        return with_access_token(url, access_token or None)

    sections: list[str] = []
    sections.append(
        f"""<!DOCTYPE html>
<html lang="en">
{base_head("iOS OTA Builds")}
<body>
  <main class="page">
    <header class="page-header">
      <p class="kicker">Builds</p>
      <h1>iOS OTA Builds</h1>
      <p class="muted">Generated {html.escape(data.get("generated_at", ""))}</p>
    </header>
"""
    )

    delete_action = u("/api/builds/delete") if enable_delete and token else ""

    for project_id, project in data.get("projects", {}).items():
        display = html.escape(project.get("display_name", project_id))
        sections.append(f'<section class="project-card"><h2>{display}</h2>')
        builds = project.get("builds", [])
        if not builds:
            sections.append('<p class="empty-state">No builds yet.</p></section>')
            continue

        sections.append(
            '<div class="table-wrap"><table class="builds-table">'
            "<thead><tr><th>Build</th><th>Branch</th><th>Commit</th>"
            "<th>Version</th><th>Actions</th></tr></thead><tbody>"
        )
        for b in builds:
            install = u(b.get("install_url") or f"{base}/{b['path']}/install.html")
            ipa = u(b.get("ipa_url") or f"{base}/{b['path']}/app.ipa")
            archive_log = u(f"{base}/{b['path']}/archive.log")
            build_name = html.escape(b.get("dir", ""))
            status_html = _status_badge(b.get("status"))
            confirm_msg = "Delete this build permanently?"

            actions = '<div class="actions">'
            if b.get("has_install") or b.get("has_ipa"):
                actions += f'<a class="btn-primary" href="{html.escape(install)}">Install</a>'
            actions += f'<a class="link-accent" href="{html.escape(ipa)}">IPA</a>'
            actions += f'<a class="link-accent" href="{html.escape(archive_log)}">Log</a>'
            if delete_action:
                actions += (
                    f'<form class="inline" method="POST" action="{html.escape(delete_action)}"'
                    f' onsubmit="return confirm(\'{confirm_msg}\');">'
                    f'<input type="hidden" name="project_id" value="{html.escape(project_id)}">'
                    f'<input type="hidden" name="build_dir" value="{html.escape(b.get("dir", ""))}">'
                    '<button type="submit" class="btn-danger">Delete</button></form>'
                )
            actions += "</div>"

            build_cell = f'<div class="build-name"><span>{build_name}</span>{status_html}</div>'
            if b.get("date"):
                build_cell += f'<br><span class="muted">{html.escape(b.get("date") or "")}</span>'

            sections.append(
                "<tr>"
                f"<td>{build_cell}</td>"
                f"<td>{html.escape(b.get('branch') or '—')}</td>"
                f"<td>{html.escape(b.get('commit') or '—')}</td>"
                f"<td>{html.escape(str(b.get('version') or '—'))} "
                f"({html.escape(str(b.get('build_number') or '—'))})</td>"
                f"<td>{actions}</td></tr>"
            )
        sections.append("</tbody></table></div></section>")

    sections.append("</main></body></html>")
    return "\n".join(sections)


def load_projects_config(projects_json: Path) -> dict:
    if not projects_json.is_file():
        return {}
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    return config.get("projects", {})
