"""Build OTA dashboard index from disk artifacts."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from auth_urls import with_access_token


def load_summary(build_dir: Path) -> dict | None:
    summary_path = build_dir / "summary.json"
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
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
                if not build_dir.is_dir():
                    continue
                if not (build_dir / "app.ipa").is_file():
                    continue
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
                builds.append(entry)

        result["projects"][project_id] = {
            "display_name": meta.get("display_name", project_id),
            "builds": builds,
        }

    return result


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
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>iOS OTA Builds</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    h1 { margin-bottom: 0.25rem; }
    .muted { color: #666; font-size: 0.9rem; }
    .project { margin: 2rem 0; border-top: 1px solid #ddd; padding-top: 1rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #eee; vertical-align: top; }
    a.btn { background: #007aff; color: #fff; padding: 0.35rem 0.75rem; border-radius: 6px; text-decoration: none; font-size: 0.85rem; display: inline-block; }
    a.link { color: #007aff; }
    button.btn-delete { background: #ff3b30; color: #fff; border: none; padding: 0.35rem 0.75rem; border-radius: 6px; font-size: 0.85rem; cursor: pointer; }
    form.inline { display: inline; margin: 0; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }
  </style>
</head>
<body>
  <h1>iOS OTA Builds</h1>
  <p class="muted">Generated """
        + html.escape(data.get("generated_at", ""))
        + "</p>"
    )

    delete_action = u("/api/builds/delete") if enable_delete and token else ""

    for project_id, project in data.get("projects", {}).items():
        display = html.escape(project.get("display_name", project_id))
        sections.append(f'<section class="project"><h2>{display}</h2>')
        builds = project.get("builds", [])
        if not builds:
            sections.append("<p class='muted'>No builds yet.</p></section>")
            continue

        sections.append(
            "<table><thead><tr><th>Build</th><th>Branch</th><th>Commit</th>"
            "<th>Version</th><th>Actions</th></tr></thead><tbody>"
        )
        for b in builds:
            install = u(b.get("install_url") or f"{base}/{b['path']}/install.html")
            ipa = u(b.get("ipa_url") or f"{base}/{b['path']}/app.ipa")
            archive_log = u(f"{base}/{b['path']}/archive.log")
            build_name = html.escape(b.get("dir", ""))
            confirm_msg = "Delete this build permanently?"

            actions = '<div class="actions">'
            if b.get("has_install") or b.get("has_ipa"):
                actions += f'<a class="btn" href="{html.escape(install)}">Install</a>'
            actions += f' <a class="link" href="{html.escape(ipa)}">IPA</a>'
            actions += f' <a class="link" href="{html.escape(archive_log)}">Log</a>'
            if delete_action:
                actions += (
                    f'<form class="inline" method="POST" action="{html.escape(delete_action)}"'
                    f' onsubmit="return confirm(\'{confirm_msg}\');">'
                    f'<input type="hidden" name="project_id" value="{html.escape(project_id)}">'
                    f'<input type="hidden" name="build_dir" value="{html.escape(b.get("dir", ""))}">'
                    '<button type="submit" class="btn-delete">Delete</button></form>'
                )
            actions += "</div>"

            sections.append(
                "<tr>"
                f"<td>{build_name}<br><span class='muted'>{html.escape(b.get('date') or '')}</span></td>"
                f"<td>{html.escape(b.get('branch') or '—')}</td>"
                f"<td>{html.escape(b.get('commit') or '—')}</td>"
                f"<td>{html.escape(str(b.get('version') or '—'))} "
                f"({html.escape(str(b.get('build_number') or '—'))})</td>"
                f"<td>{actions}</td></tr>"
            )
        sections.append("</tbody></table></section>")

    sections.append("</body></html>")
    return "\n".join(sections)


def load_projects_config(projects_json: Path) -> dict:
    if not projects_json.is_file():
        return {}
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    return config.get("projects", {})
