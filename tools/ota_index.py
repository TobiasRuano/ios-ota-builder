"""Build OTA dashboard index from disk artifacts."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from auth_urls import with_access_token
from ui_theme import base_head

_COPY_SCRIPT = """<script>
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".btn-copy");
  if (!btn) return;
  var url = btn.getAttribute("data-copy-url");
  if (!url) return;
  function showCopied() {
    var original = btn.getAttribute("data-copy-label") || btn.textContent;
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    btn.setAttribute("aria-label", "Copied to clipboard");
    setTimeout(function () {
      btn.textContent = original;
      btn.classList.remove("copied");
      btn.setAttribute("aria-label", btn.getAttribute("data-copy-aria") || original);
    }, 1500);
  }
  function fallback() {
    var ta = document.createElement("textarea");
    ta.value = url;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      showCopied();
    } catch (err) {}
    document.body.removeChild(ta);
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(showCopied).catch(fallback);
  } else {
    fallback();
  }
});
</script>"""


def load_summary(build_dir: Path) -> dict | None:
    summary_path = build_dir / "summary.json"
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


_COMPACT_BUILD_DIR_RE = re.compile(r"^\d{2}-\d{2}-\d+$")


def _is_compact_build_dir(name: str) -> bool:
    return bool(_COMPACT_BUILD_DIR_RE.match(name))


def _build_sort_key(entry: dict, build_dir: Path) -> float:
    date_str = entry.get("date")
    if date_str:
        try:
            return datetime.fromisoformat(str(date_str).replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return build_dir.stat().st_mtime


def _resolve_configuration(build_dir_name: str, summary: dict | None) -> str | None:
    if summary and summary.get("configuration"):
        return str(summary["configuration"])
    if build_dir_name.endswith("-debug"):
        return "Debug"
    return "Release"


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _format_ipa_size(bytes_: int | None) -> str:
    if bytes_ is None:
        return "—"
    try:
        size = int(bytes_)
    except (TypeError, ValueError):
        return "—"
    if size <= 0:
        return "—"
    mb = size / (1024 * 1024)
    if mb >= 100:
        return f"{mb:.0f} MB"
    if mb >= 10:
        return f"{mb:.1f} MB"
    return f"{mb:.2f} MB"


def _build_entry_if_valid(build_dir: Path, project_id: str) -> dict | None:
    if not build_dir.is_dir():
        return None
    if not (build_dir / "app.ipa").is_file():
        return None
    summary = load_summary(build_dir)
    rel = f"{project_id}/{build_dir.name}"
    entry: dict = {
        "dir": build_dir.name,
        "path": rel,
        "project_id": project_id,
        "has_ipa": True,
        "has_install": (build_dir / "install.html").is_file(),
        "configuration": _resolve_configuration(build_dir.name, summary),
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
                "duration_seconds": summary.get("duration_seconds"),
                "ipa_size_bytes": summary.get("ipa_size_bytes"),
            }
        )
        if summary.get("configuration"):
            entry["configuration"] = summary["configuration"]
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

    candidates: list[tuple[dict, float]] = []
    for build_dir in project_dir.iterdir():
        entry = _build_entry_if_valid(build_dir, project_id)
        if entry is None or entry.get("status") != "success":
            continue
        candidates.append((entry, _build_sort_key(entry, build_dir)))

    if not candidates:
        return None

    entry = max(candidates, key=lambda item: item[1])[0]
    return {
        "project_id": project_id,
        "build_dir": entry["dir"],
        "path": entry["path"],
    }



def collect_builds(ota_dir: Path, projects_config: dict) -> dict:
    result: dict = {
        "projects": {},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    for project_id, meta in projects_config.items():
        project_dir = ota_dir / project_id
        builds: list[dict] = []
        if project_dir.is_dir():
            ranked: list[tuple[dict, float]] = []
            for build_dir in project_dir.iterdir():
                entry = _build_entry_if_valid(build_dir, project_id)
                if entry is not None:
                    ranked.append((entry, _build_sort_key(entry, build_dir)))
            ranked.sort(key=lambda item: item[1], reverse=True)
            builds = [entry for entry, _ in ranked]

        latest_marked = False
        for entry in builds:
            if not latest_marked and entry.get("status") == "success":
                entry["is_latest"] = True
                latest_marked = True

        result["projects"][project_id] = {
            "display_name": meta.get("display_name", project_id),
            "builds": builds,
        }

    return result


def _copy_button(url: str, *, aria_label: str, label: str = "Copy") -> str:
    return (
        f'<button type="button" class="btn-copy" '
        f'data-copy-url="{html.escape(url, quote=True)}" '
        f'data-copy-label="{html.escape(label)}" '
        f'data-copy-aria="{html.escape(aria_label)}" '
        f'aria-label="{html.escape(aria_label)}">{html.escape(label)}</button>'
    )


def _build_badges(build: dict) -> str:
    badges: list[str] = []
    status = build.get("status")

    if status == "success":
        badges.append(
            '<span class="status-badge status-success">'
            '<span class="status-dot" aria-hidden="true"></span>success</span>'
        )
    elif status == "failure":
        badges.append('<span class="status-badge badge-failed">failed</span>')
    elif status:
        label = html.escape(str(status))
        badges.append(f'<span class="status-badge">{label}</span>')

    configuration = build.get("configuration")
    if configuration == "Debug":
        badges.append('<span class="status-badge badge-debug">Debug</span>')
    elif configuration == "Release":
        badges.append('<span class="status-badge badge-release">Release</span>')

    if build.get("is_latest"):
        badges.append('<span class="status-badge badge-latest">Latest</span>')

    if not badges:
        return ""
    return f'<div class="badge-group">{"".join(badges)}</div>'


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
        builds = project.get("builds", [])
        if not builds:
            sections.append(
                f'<section class="project-card"><h2>{display}</h2>'
                '<p class="empty-state">No builds yet.</p></section>'
            )
            continue

        has_successful = any(b.get("status") == "success" for b in builds)
        header_actions = ""
        if has_successful:
            latest_install_url = u(f"{base}/latest/{project_id}")
            header_actions = _copy_button(
                latest_install_url,
                aria_label=f"Copy latest install link for {project.get('display_name', project_id)}",
                label="Copy latest",
            )

        sections.append(
            f'<section class="project-card">'
            f'<div class="project-card-header"><h2>{display}</h2>{header_actions}</div>'
        )

        sections.append(
            '<div class="table-wrap"><table class="builds-table">'
            "<thead><tr><th>Build</th><th>Branch</th><th>Commit</th>"
            "<th>Version</th><th>Duration</th><th>Size</th><th>Actions</th></tr></thead><tbody>"
        )
        for b in builds:
            install = u(b.get("install_url") or f"{base}/{b['path']}/install.html")
            ipa = u(b.get("ipa_url") or f"{base}/{b['path']}/app.ipa")
            archive_log = u(f"{base}/{b['path']}/archive.log")
            build_name = html.escape(b.get("dir", ""))
            badges_html = _build_badges(b)
            confirm_msg = "Delete this build permanently?"

            actions = '<div class="actions">'
            if b.get("has_install") or b.get("has_ipa"):
                actions += f'<a class="btn-primary" href="{html.escape(install)}">Install</a>'
                actions += _copy_button(install, aria_label="Copy install link")
            actions += f'<a class="link-accent" href="{html.escape(ipa)}">IPA</a>'
            actions += _copy_button(ipa, aria_label="Copy IPA link")
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

            build_cell = f'<div class="build-name"><span>{build_name}</span>{badges_html}</div>'
            if b.get("date") and not _is_compact_build_dir(b.get("dir", "")):
                build_cell += f'<br><span class="muted">{html.escape(b.get("date") or "")}</span>'

            duration_cell = html.escape(_format_duration(b.get("duration_seconds")))
            size_cell = html.escape(_format_ipa_size(b.get("ipa_size_bytes")))

            sections.append(
                "<tr>"
                f"<td>{build_cell}</td>"
                f"<td>{html.escape(b.get('branch') or '—')}</td>"
                f"<td>{html.escape(b.get('commit') or '—')}</td>"
                f"<td>{html.escape(str(b.get('version') or '—'))} "
                f"({html.escape(str(b.get('build_number') or '—'))})</td>"
                f'<td class="meta-cell">{duration_cell}</td>'
                f'<td class="meta-cell">{size_cell}</td>'
                f"<td>{actions}</td></tr>"
            )
        sections.append("</tbody></table></div></section>")

    sections.append(f"</main>\n{_COPY_SCRIPT}\n</body></html>")
    return "\n".join(sections)


def load_projects_config(projects_json: Path) -> dict:
    if not projects_json.is_file():
        return {}
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    return config.get("projects", {})
