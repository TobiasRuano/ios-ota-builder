"""Dynamically serve install.html and manifest.plist with the current access token."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from auth_urls import with_access_token  # noqa: E402
from generate_manifest import build_install_html, build_manifest  # noqa: E402
from ota_index import _find_ipa_file, _resolve_configuration, load_summary, load_projects_config  # noqa: E402


def parse_ota_artifact_path(path: str) -> tuple[str, str, str] | None:
    """Return (project_id, build_dir_name, artifact) for OTA artifact paths."""
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) != 3:
        return None
    project_id, build_dir_name, artifact = parts
    if artifact not in ("install.html", "manifest.plist"):
        return None
    if "/" in project_id or "/" in build_dir_name:
        return None
    return project_id, build_dir_name, artifact


def render_ota_artifact(
    *,
    ota_dir: Path,
    projects_json: Path,
    base_url: str,
    token: str | None,
    project_id: str,
    build_dir_name: str,
    artifact: str,
) -> tuple[bytes, str] | None:
    build_dir = (ota_dir / project_id / build_dir_name).resolve()
    try:
        build_dir.relative_to(ota_dir.resolve())
    except ValueError:
        return None
    if not build_dir.is_dir():
        return None

    summary = load_summary(build_dir)
    if summary is None or summary.get("status") != "success":
        return None
    if _find_ipa_file(build_dir) is None:
        return None

    projects = load_projects_config(projects_json)
    project = projects.get(project_id, {})
    bundle_id = project.get("bundle_id", "")
    if not bundle_id:
        return None

    display_name = str(summary.get("display_name") or project.get("display_name") or project_id)
    version = str(summary.get("version") or "0")
    build_number = str(summary.get("build_number") or "0")
    branch = str(summary.get("branch") or "—")
    commit = str(summary.get("commit") or "—")
    build_date = str(summary.get("date") or "")
    configuration = _resolve_configuration(build_dir_name, summary) or "Release"
    release_notes = str(summary.get("release_notes") or "")
    ipa_file = _find_ipa_file(build_dir)
    ipa_filename = summary.get("ipa_filename") or (ipa_file.name if ipa_file else "app.ipa")

    base = base_url.rstrip("/") if base_url else ""
    rel = f"{project_id}/{build_dir_name}"
    encoded_ipa = quote(str(ipa_filename), safe="")
    ipa_url = with_access_token(f"{base}/{rel}/{encoded_ipa}", token)
    manifest_url = with_access_token(f"{base}/{rel}/manifest.plist", token)
    install_page_url = with_access_token(f"{base}/{rel}/install.html", token)
    icon_url = None
    if (build_dir / "icon.png").is_file():
        icon_url = with_access_token(f"{base}/{rel}/icon.png", token)

    bundle_version = f"{version}.{build_number}"

    if artifact == "manifest.plist":
        body = build_manifest(
            title=display_name,
            bundle_id=bundle_id,
            bundle_version=bundle_version,
            ipa_url=ipa_url,
        )
        return body, "application/xml"

    html_body = build_install_html(
        title=display_name,
        manifest_url=manifest_url,
        ipa_url=ipa_url,
        install_page_url=install_page_url,
        version=version,
        build_number=build_number,
        branch=branch,
        commit=commit,
        build_date=build_date,
        configuration=configuration,
        icon_url=icon_url,
        release_notes=release_notes,
    )
    return html_body.encode("utf-8"), "text/html; charset=utf-8"
