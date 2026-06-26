"""Build OTA dashboard index from disk artifacts."""

from __future__ import annotations

import html
import json
import re
import shutil
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

_DROPDOWN_SCRIPT = """<script>
(function () {
  var GAP = 6;

  function resetMenu(menu) {
    menu.hidden = true;
    menu.classList.remove("is-open", "action-dropdown-menu-up");
    menu.style.position = "";
    menu.style.top = "";
    menu.style.bottom = "";
    menu.style.right = "";
    menu.style.left = "";
    menu.style.minWidth = "";
  }

  function closeAllMenus() {
    document.querySelectorAll(".action-dropdown-menu").forEach(resetMenu);
    document.querySelectorAll(".action-dropdown-trigger").forEach(function (trigger) {
      trigger.setAttribute("aria-expanded", "false");
    });
  }

  function positionMenu(trigger, menu) {
    menu.classList.remove("action-dropdown-menu-up");
    menu.style.position = "fixed";
    menu.style.left = "";
    menu.style.top = "";
    menu.style.bottom = "";

    var rect = trigger.getBoundingClientRect();
    menu.style.right = (window.innerWidth - rect.right) + "px";
    menu.style.minWidth = Math.max(rect.width, 184) + "px";
    menu.hidden = false;
    menu.classList.add("is-open");

    var menuHeight = menu.offsetHeight;
    var spaceBelow = window.innerHeight - rect.bottom - GAP;
    var spaceAbove = rect.top - GAP;

    if (spaceBelow >= menuHeight || spaceBelow >= spaceAbove) {
      menu.style.top = (rect.bottom + GAP) + "px";
    } else {
      menu.classList.add("action-dropdown-menu-up");
      menu.style.bottom = (window.innerHeight - rect.top + GAP) + "px";
    }
  }

  document.addEventListener("click", function (e) {
    var trigger = e.target.closest(".action-dropdown-trigger");
    if (trigger) {
      e.stopPropagation();
      var dropdown = trigger.closest(".action-dropdown");
      var menu = dropdown.querySelector(".action-dropdown-menu");
      var isOpen = !menu.hidden;
      closeAllMenus();
      if (!isOpen) {
        positionMenu(trigger, menu);
        trigger.setAttribute("aria-expanded", "true");
      }
      return;
    }

    if (e.target.closest(".action-menu-item")) {
      closeAllMenus();
      return;
    }

    if (!e.target.closest(".action-dropdown")) {
      closeAllMenus();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeAllMenus();
    }
  });

  window.addEventListener("resize", closeAllMenus);
  document.addEventListener("scroll", closeAllMenus, true);
})();
</script>"""

_RESTART_SCRIPT = """<script>
(function () {
  var POLL_INTERVAL_MS = 2000;
  var TIMEOUT_MS = 30000;

  function pollHealth(onReady, onTimeout) {
    var started = Date.now();
    function check() {
      fetch("/health", { cache: "no-store" })
        .then(function (resp) {
          if (!resp.ok) throw new Error("health not ok");
          return resp.json();
        })
        .then(function (data) {
          if (data && data.ok) {
            onReady();
            return;
          }
          throw new Error("health not ok");
        })
        .catch(function () {
          if (Date.now() - started >= TIMEOUT_MS) {
            onTimeout();
            return;
          }
          setTimeout(check, POLL_INTERVAL_MS);
        });
    }
    setTimeout(check, POLL_INTERVAL_MS);
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-restart-server");
    if (!btn || btn.disabled) return;

    var action = btn.getAttribute("data-restart-action");
    if (!action) return;

    if (!confirm("Restart the OTA server? The dashboard will be briefly unavailable.")) {
      return;
    }

    var panel = btn.closest(".status-panel");
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Restarting…";
    if (panel) panel.classList.add("status-panel-restarting");

    fetch(action, { method: "POST" })
      .then(function (resp) {
        if (!resp.ok && resp.status !== 202) {
          throw new Error("restart request failed");
        }
        pollHealth(
          function () { window.location.reload(); },
          function () {
            btn.disabled = false;
            btn.textContent = originalText;
            if (panel) panel.classList.remove("status-panel-restarting");
            alert("Server did not come back within 30 seconds. Check the Mac or run ./server/restart_server.sh.");
          }
        );
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = originalText;
        if (panel) panel.classList.remove("status-panel-restarting");
        alert("Could not schedule server restart.");
      });
  });
})();
</script>"""

_BUILD_SCRIPT = """<script>
(function () {
  var POLL_MS = 4000;

  function apiUrl(path) {
    return path + (path.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(window.__OTA_TOKEN || "");
  }

  function setStatus(panel, text, isWarn) {
    var el = panel.querySelector(".build-git-status");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("warn", !!isWarn);
  }

  function setProgress(panel, text, active) {
    var el = panel.querySelector(".build-panel-progress");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("is-active", !!active);
  }

  function fillBranchSelect(select, data, current) {
    while (select.options.length) select.remove(0);
    var groups = [
      ["Local", data.local || []],
      ["Remote", data.remote || []]
    ];
    groups.forEach(function (pair) {
      var label = pair[0];
      var branches = pair[1];
      if (!branches.length) return;
      var og = document.createElement("optgroup");
      og.label = label;
      branches.forEach(function (b) {
        var opt = document.createElement("option");
        opt.value = b;
        opt.textContent = b;
        if (b === current) opt.selected = true;
        og.appendChild(opt);
      });
      select.appendChild(og);
    });
    if (!select.options.length) {
      var empty = document.createElement("option");
      empty.value = "";
      empty.textContent = current || "(current branch)";
      select.appendChild(empty);
    }
  }

  function findPanelForToggle(toggle) {
    var panelId = toggle.getAttribute("aria-controls");
    if (panelId) {
      var byId = document.getElementById(panelId);
      if (byId) return byId;
    }
    var card = toggle.closest(".project-card");
    return card ? card.querySelector(".build-panel") : null;
  }

  function findToggleForPanel(panel) {
    var panelId = panel.id;
    if (!panelId) return null;
    var card = panel.closest(".project-card");
    if (!card) return null;
    return card.querySelector('.btn-new-build-toggle[aria-controls="' + panelId + '"]');
  }

  function openBuildPanel(panel) {
    panel.hidden = false;
    var toggle = findToggleForPanel(panel);
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    if (!panel.dataset.statusLoaded) {
      loadGitStatus(panel);
    }
  }

  function closeBuildPanel(panel) {
    panel.hidden = true;
    var toggle = findToggleForPanel(panel);
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  }

  function toggleBuildPanel(panel) {
    if (panel.hidden) {
      openBuildPanel(panel);
    } else {
      closeBuildPanel(panel);
    }
  }

  function loadGitStatus(panel) {
    var projectId = panel.getAttribute("data-project-id");
    var statusUrl = panel.getAttribute("data-git-status-url");
    if (!statusUrl) return;
    fetch(apiUrl(statusUrl))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          setStatus(panel, data.error, true);
          return;
        }
        panel.dataset.statusLoaded = "1";
        var branch = data.branch || "unknown";
        var commit = data.commit || "unknown";
        var parts = [branch + " @ " + commit];
        if (data.dirty_count > 0) {
          parts.push(data.dirty_count + " uncommitted change(s)");
        }
        if (data.has_conflicts) {
          parts.push("merge conflicts");
        }
        if (data.build_locked) {
          parts.push("build lock active");
        }
        setStatus(panel, parts.join(" · "), data.dirty_count > 0 || data.has_conflicts);
        var select = panel.querySelector(".build-branch-select");
        if (select && !select.dataset.loaded) {
          select.dataset.loaded = "1";
          var branchesUrl = panel.getAttribute("data-git-branches-url");
          if (branchesUrl) {
            fetch(apiUrl(branchesUrl))
              .then(function (r) { return r.json(); })
              .then(function (br) { fillBranchSelect(select, br, branch); })
              .catch(function () {});
          }
        }
        var startBtn = panel.querySelector(".btn-build-start");
        if (startBtn) {
          startBtn.disabled = !!(data.has_conflicts || data.active_job);
        }
        if (data.active_job && data.active_job.id) {
          pollJob(panel, data.active_job.id);
        }
      })
      .catch(function () {
        setStatus(panel, "Could not load git status", true);
      });
  }

  function pollJob(panel, jobId) {
    var jobsUrl = panel.getAttribute("data-jobs-url");
    if (!jobsUrl) return;
    var jobUrl = jobsUrl.replace(/\\/?$/, "") + "/" + encodeURIComponent(jobId);
    setProgress(panel, "Build in progress…", true);
    var startBtn = panel.querySelector(".btn-build-start");
    if (startBtn) startBtn.disabled = true;

    function check() {
      fetch(apiUrl(jobUrl))
        .then(function (r) { return r.json(); })
        .then(function (job) {
          if (!job || job.error) return;
          var st = job.status || "";
          if (st === "queued" || st === "preparing" || st === "building") {
            setProgress(panel, "Build " + st + "…", true);
            setTimeout(check, POLL_MS);
            return;
          }
          if (st === "success") {
            setProgress(panel, "Build succeeded — refreshing…", false);
            setTimeout(function () { window.location.reload(); }, 1200);
            return;
          }
          setProgress(panel, job.error || "Build failed", true);
          if (startBtn) startBtn.disabled = false;
          loadGitStatus(panel);
        })
        .catch(function () {
          setTimeout(check, POLL_MS);
        });
    }
    check();
  }

  document.querySelectorAll(".build-panel").forEach(function (panel) {
    var statusUrl = panel.getAttribute("data-git-status-url");
    if (!statusUrl) return;
    fetch(apiUrl(statusUrl))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.active_job && data.active_job.id) {
          openBuildPanel(panel);
        }
      })
      .catch(function () {});
  });

  document.addEventListener("click", function (e) {
    var toggleBtn = e.target.closest(".btn-new-build-toggle");
    if (toggleBtn) {
      var togglePanel = findPanelForToggle(toggleBtn);
      if (togglePanel) toggleBuildPanel(togglePanel);
      return;
    }

    var cancelBtn = e.target.closest(".btn-build-cancel");
    if (cancelBtn) {
      var cancelPanel = cancelBtn.closest(".build-panel");
      if (cancelPanel) closeBuildPanel(cancelPanel);
      return;
    }

    var fetchBtn = e.target.closest(".btn-build-fetch");
    if (fetchBtn) {
      var panel = fetchBtn.closest(".build-panel");
      var url = panel.getAttribute("data-git-fetch-url");
      fetchBtn.disabled = true;
      fetch(apiUrl(url), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "project_id=" + encodeURIComponent(panel.getAttribute("data-project-id"))
      })
        .then(function (r) { return r.json(); })
        .then(function () {
          var select = panel.querySelector(".build-branch-select");
          if (select) select.dataset.loaded = "";
          loadGitStatus(panel);
        })
        .finally(function () { fetchBtn.disabled = false; });
      return;
    }

    var startBtn = e.target.closest(".btn-build-start");
    if (!startBtn || startBtn.disabled) return;
    var panel = startBtn.closest(".build-panel");
    var triggerUrl = panel.getAttribute("data-trigger-url");
    var branch = (panel.querySelector(".build-branch-select") || {}).value || "";
    var gitMode = (panel.querySelector(".build-git-mode") || {}).value || "auto";
    var config = (panel.querySelector(".build-configuration") || {}).value || "";
    var body = "project_id=" + encodeURIComponent(panel.getAttribute("data-project-id"))
      + "&branch=" + encodeURIComponent(branch)
      + "&git_mode=" + encodeURIComponent(gitMode)
      + "&configuration=" + encodeURIComponent(config);
    startBtn.disabled = true;
    fetch(apiUrl(triggerUrl), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.id) {
          throw new Error((res.j && res.j.error) || "trigger failed");
        }
        pollJob(panel, res.j.id);
      })
      .catch(function (err) {
        setProgress(panel, err.message || "Could not start build", true);
        startBtn.disabled = false;
      });
  });
})();
</script>"""

_CHEVRON_SVG = (
    '<svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<path fill="currentColor" d="M4.427 6.573a.25.25 0 0 0-.035.385l3.85 3.85a.25.25 0 0 0 '
    '.354 0l3.85-3.85a.25.25 0 0 0-.177-.427H4.604a.25.25 0 0 0-.177.073z"/>'
    "</svg>"
)


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


def _parse_build_number(entry: dict, build_dir: Path) -> int:
    build_number = entry.get("build_number")
    if build_number is not None:
        try:
            return int(build_number)
        except (TypeError, ValueError):
            pass

    dir_name = entry.get("dir") or build_dir.name
    if _is_compact_build_dir(dir_name):
        try:
            return int(dir_name.rsplit("-", 1)[-1])
        except ValueError:
            pass
    return 0


def _build_sort_key(entry: dict, build_dir: Path) -> tuple[float, int]:
    date_str = entry.get("date")
    if date_str:
        try:
            timestamp = datetime.fromisoformat(str(date_str).replace("Z", "+00:00")).timestamp()
            return (timestamp, _parse_build_number(entry, build_dir))
        except ValueError:
            pass
    return (build_dir.stat().st_mtime, _parse_build_number(entry, build_dir))


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


def commit_url(
    repo_url: str | None,
    repo_type: str | None,
    sha: str | None,
) -> str | None:
    if not repo_url or not sha or sha == "unknown":
        return None
    base = repo_url.rstrip("/")
    provider = (repo_type or "github").lower()
    if provider == "gitlab":
        return f"{base}/-/commit/{sha}"
    return f"{base}/commit/{sha}"


def _format_commit_cell(build: dict, project: dict) -> str:
    short_commit = build.get("commit")
    link_sha = build.get("commit_full") or short_commit
    if not link_sha or link_sha == "unknown":
        return "—"

    display = str(short_commit or link_sha)
    url = commit_url(project.get("repo_url"), project.get("repo_type"), str(link_sha))
    if url:
        return (
            f'<a href="{html.escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">'
            f"{html.escape(display)}</a>"
        )
    return html.escape(display)


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


_BUILDS_TABLE_COLGROUP = (
    "<colgroup>"
    '<col class="col-build">'
    '<col class="col-branch">'
    '<col class="col-commit">'
    '<col class="col-version">'
    '<col class="col-duration">'
    '<col class="col-size">'
    '<col class="col-actions">'
    "</colgroup>"
)


def _format_dashboard_timestamp(iso: str) -> str:
    if not iso or not str(iso).strip():
        return "—"
    raw = str(iso).strip()
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return raw


def _truncate_table_cell(value: str | None, *, data_label: str) -> str:
    text = (value or "").strip() or "—"
    escaped = html.escape(text)
    title_attr = f' title="{html.escape(text)}"' if text != "—" else ""
    return (
        f'<td class="cell-truncate" data-label="{data_label}"{title_attr}>{escaped}</td>'
    )


def _find_ipa_file(build_dir: Path) -> Path | None:
    legacy = build_dir / "app.ipa"
    if legacy.is_file():
        return legacy
    ipas = sorted(build_dir.glob("*.ipa"))
    if len(ipas) == 1:
        return ipas[0]
    return None


def _fallback_build_label(entry: dict, build_dir: Path) -> str:
    if entry.get("build_label"):
        return str(entry["build_label"])
    build_number = _parse_build_number(entry, build_dir)
    if build_number > 0:
        return f"#{build_number}"
    return entry.get("dir") or build_dir.name


def _apply_summary_fields(entry: dict, summary: dict) -> None:
    entry.update(
        {
            "status": summary.get("status"),
            "branch": summary.get("branch"),
            "commit": summary.get("commit"),
            "commit_full": summary.get("commit_full"),
            "date": summary.get("date"),
            "version": summary.get("version"),
            "build_number": summary.get("build_number"),
            "install_url": summary.get("install_url"),
            "manifest_url": summary.get("manifest_url"),
            "ipa_url": summary.get("ipa_url"),
            "duration_seconds": summary.get("duration_seconds"),
            "ipa_size_bytes": summary.get("ipa_size_bytes"),
            "stage": summary.get("stage"),
            "icon_path": summary.get("icon_path"),
        }
    )
    if summary.get("ipa_filename"):
        entry["ipa_filename"] = summary["ipa_filename"]
    if summary.get("build_label"):
        entry["build_label"] = summary["build_label"]
    if summary.get("configuration"):
        entry["configuration"] = summary["configuration"]
    if summary.get("release_notes"):
        entry["release_notes"] = summary["release_notes"]


def _apply_icon_fields(entry: dict, build_dir: Path, project_id: str) -> None:
    has_icon_file = (build_dir / "icon.png").is_file()
    entry["has_icon"] = has_icon_file
    if has_icon_file and not entry.get("icon_path"):
        entry["icon_path"] = f"/{project_id}/{build_dir.name}/icon.png"


def _pick_log_filename(build_dir: Path) -> str | None:
    for name in ("archive.log", "export.log", "build.log"):
        if (build_dir / name).is_file():
            return name
    return None


def _build_failure_entry(
    build_dir: Path, project_id: str, summary: dict
) -> dict:
    rel = f"{project_id}/{build_dir.name}"
    entry: dict = {
        "dir": build_dir.name,
        "path": rel,
        "project_id": project_id,
        "has_ipa": False,
        "has_install": False,
        "has_diagnostics": (build_dir / "diagnostics.md").is_file(),
        "configuration": _resolve_configuration(build_dir.name, summary),
    }
    log_filename = _pick_log_filename(build_dir)
    if log_filename:
        entry["log_filename"] = log_filename
        entry["has_log"] = True
    else:
        entry["has_log"] = False
    _apply_summary_fields(entry, summary)
    _apply_icon_fields(entry, build_dir, project_id)
    entry["build_label"] = _fallback_build_label(entry, build_dir)
    return entry


def _build_entry_if_valid(build_dir: Path, project_id: str) -> dict | None:
    if not build_dir.is_dir():
        return None

    summary = load_summary(build_dir)
    ipa_file = _find_ipa_file(build_dir)

    if ipa_file is not None:
        rel = f"{project_id}/{build_dir.name}"
        ipa_filename = ipa_file.name
        entry: dict = {
            "dir": build_dir.name,
            "path": rel,
            "project_id": project_id,
            "has_ipa": True,
            "has_install": (build_dir / "install.html").is_file(),
            "configuration": _resolve_configuration(build_dir.name, summary),
            "ipa_filename": ipa_filename,
        }
        if summary:
            _apply_summary_fields(entry, summary)
        _apply_icon_fields(entry, build_dir, project_id)
        entry["build_label"] = _fallback_build_label(entry, build_dir)
        return entry

    if summary and summary.get("status") == "failure":
        return _build_failure_entry(build_dir, project_id, summary)

    return None


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

    candidates: list[tuple[dict, tuple[float, int]]] = []
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
            ranked: list[tuple[dict, tuple[float, int]]] = []
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
            "repo_url": meta.get("repo_url"),
            "repo_type": meta.get("repo_type", "github"),
            "builds": builds,
        }

    return result


def _copy_button(
    url: str,
    *,
    aria_label: str,
    label: str = "Copy",
    menu_item: bool = False,
) -> str:
    classes = "action-menu-item btn-copy" if menu_item else "btn-copy"
    role_attr = 'role="menuitem" ' if menu_item else ""
    return (
        f'<button type="button" class="{classes}" '
        f'{role_attr}'
        f'data-copy-url="{html.escape(url, quote=True)}" '
        f'data-copy-label="{html.escape(label)}" '
        f'data-copy-aria="{html.escape(aria_label)}" '
        f'aria-label="{html.escape(aria_label)}">{html.escape(label)}</button>'
    )


def _build_actions_menu(
    *,
    install: str,
    ipa: str,
    archive_log: str,
    has_install: bool,
    has_ipa: bool,
    delete_action: str,
    project_id: str,
    build_dir: str,
    confirm_msg: str = "Delete this build permanently?",
) -> str:
    can_install = has_install or has_ipa
    if can_install:
        primary = (
            f'<a class="btn-primary action-split-primary" href="{html.escape(install)}">Install</a>'
        )
    else:
        primary = (
            f'<a class="btn-primary action-split-primary" href="{html.escape(ipa)}">'
            "Download IPA</a>"
        )

    menu_items: list[str] = []
    if can_install:
        menu_items.append(
            _copy_button(
                install,
                aria_label="Copy install link",
                label="Copy install link",
                menu_item=True,
            )
        )
    menu_items.append(
        f'<a class="action-menu-item" role="menuitem" href="{html.escape(ipa)}">Download IPA</a>'
    )
    menu_items.append(
        _copy_button(
            ipa,
            aria_label="Copy IPA link",
            label="Copy IPA link",
            menu_item=True,
        )
    )
    menu_items.append(
        f'<a class="action-menu-item" role="menuitem" href="{html.escape(archive_log)}">'
        "View log</a>"
    )

    delete_html = ""
    if delete_action:
        delete_html = (
            '<div class="action-menu-divider" role="separator"></div>'
            f'<form class="action-menu-form" method="POST" action="{html.escape(delete_action)}"'
            f' onsubmit="return confirm(\'{confirm_msg}\');">'
            f'<input type="hidden" name="project_id" value="{html.escape(project_id)}">'
            f'<input type="hidden" name="build_dir" value="{html.escape(build_dir)}">'
            '<button type="submit" class="action-menu-item action-menu-item-danger" '
            'role="menuitem">Delete</button></form>'
        )

    menu_content = "".join(menu_items) + delete_html

    return (
        '<div class="actions">'
        '<div class="action-split">'
        f"{primary}"
        '<div class="action-dropdown">'
        '<button type="button" class="action-dropdown-trigger" aria-label="More actions" '
        'aria-expanded="false" aria-haspopup="menu">'
        f"{_CHEVRON_SVG}"
        "</button>"
        f'<div class="action-dropdown-menu" role="menu" hidden>{menu_content}</div>'
        "</div>"
        "</div>"
        "</div>"
    )


def _build_failure_actions_menu(
    *,
    diagnostics: str,
    log_url: str,
    has_diagnostics: bool,
    has_log: bool,
    delete_action: str,
    project_id: str,
    build_dir: str,
    confirm_msg: str = "Delete this build permanently?",
) -> str:
    if has_diagnostics:
        primary = (
            f'<a class="btn-primary action-split-primary" href="{html.escape(diagnostics)}">'
            "Diagnostics</a>"
        )
    else:
        primary = '<span class="btn-primary action-split-primary is-disabled">Diagnostics</span>'

    menu_items: list[str] = []
    if has_log:
        menu_items.append(
            f'<a class="action-menu-item" role="menuitem" href="{html.escape(log_url)}">'
            "View log</a>"
        )

    delete_html = ""
    if delete_action:
        delete_html = (
            '<div class="action-menu-divider" role="separator"></div>'
            f'<form class="action-menu-form" method="POST" action="{html.escape(delete_action)}"'
            f' onsubmit="return confirm(\'{confirm_msg}\');">'
            f'<input type="hidden" name="project_id" value="{html.escape(project_id)}">'
            f'<input type="hidden" name="build_dir" value="{html.escape(build_dir)}">'
            '<button type="submit" class="action-menu-item action-menu-item-danger" '
            'role="menuitem">Delete</button></form>'
        )

    menu_content = "".join(menu_items) + delete_html
    has_menu = bool(menu_items) or bool(delete_html)

    if has_menu:
        dropdown = (
            '<div class="action-dropdown">'
            '<button type="button" class="action-dropdown-trigger" aria-label="More actions" '
            'aria-expanded="false" aria-haspopup="menu">'
            f"{_CHEVRON_SVG}"
            "</button>"
            f'<div class="action-dropdown-menu" role="menu" hidden>{menu_content}</div>'
            "</div>"
        )
    else:
        dropdown = ""

    return (
        '<div class="actions">'
        '<div class="action-split">'
        f"{primary}"
        f"{dropdown}"
        "</div>"
        "</div>"
    )


def _render_build_notes(build: dict) -> str:
    notes = build.get("release_notes")
    if not notes or not str(notes).strip():
        return ""
    safe_notes = html.escape(str(notes).strip())
    return (
        '<details class="build-notes">'
        "<summary>Release notes</summary>"
        f'<pre class="build-notes-body">{safe_notes}</pre>'
        "</details>"
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


def collect_disk_stats(ota_dir: Path, *, min_disk_mb: int = 5000) -> dict:
    try:
        ota_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(ota_dir)
    except OSError:
        return {
            "free_gb": "—",
            "free_mb": 0,
            "used_percent": None,
            "ok": False,
            "threshold_mb": min_disk_mb,
            "unavailable": True,
        }

    free_mb = usage.free // (1024 * 1024)
    total = usage.total
    used_percent = round((total - usage.free) / total * 100, 1) if total else 0.0
    return {
        "free_gb": f"{free_mb / 1024:.1f}",
        "free_mb": free_mb,
        "used_percent": used_percent,
        "ok": free_mb >= min_disk_mb,
        "threshold_mb": min_disk_mb,
    }


def format_uptime(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _status_dot(*, ok: bool) -> str:
    dot_class = "status-dot" if ok else "status-dot status-dot-warning"
    return f'<span class="{dot_class}" aria-hidden="true"></span>'


def render_status_panel(status: dict, *, restart_action: str = "") -> str:
    disk = status.get("disk", {})
    threshold_mb = disk.get("threshold_mb", 5000)
    panel_class = "status-panel"
    if not disk.get("ok", True):
        panel_class += " status-panel-warning"

    rows: list[str] = []

    if disk.get("unavailable"):
        disk_text = "Disk: unavailable"
        disk_ok = False
    else:
        used = disk.get("used_percent")
        used_suffix = f" ({used:g}% used)" if used is not None else ""
        disk_text = f"Disk: {html.escape(str(disk.get('free_gb', '—')))} GB free{used_suffix}"
        disk_ok = bool(disk.get("ok", True))
    rows.append(
        f'<div class="status-panel-item">{_status_dot(ok=disk_ok)}'
        f'<span>{disk_text}</span></div>'
    )

    uptime_seconds = status.get("uptime_seconds")
    if uptime_seconds is not None:
        uptime_label = html.escape(format_uptime(int(uptime_seconds)))
        rows.append(
            f'<div class="status-panel-item">{_status_dot(ok=True)}'
            f'<span>Uptime: {uptime_label}</span></div>'
        )

    writable = status.get("ota_builds_dir_writable")
    if writable is not None:
        writable_ok = bool(writable)
        writable_text = "Builds dir: writable" if writable_ok else "Builds dir: not writable"
        rows.append(
            f'<div class="status-panel-item">{_status_dot(ok=writable_ok)}'
            f'<span>{writable_text}</span></div>'
        )

    tunnel = status.get("tunnel")
    if tunnel is not None:
        tunnel_ok = bool(tunnel.get("reachable"))
        tunnel_text = "Tunnel: reachable" if tunnel_ok else "Tunnel: unreachable"
        rows.append(
            f'<div class="status-panel-item">{_status_dot(ok=tunnel_ok)}'
            f'<span>{tunnel_text}</span></div>'
        )

    warning_html = ""
    if not disk.get("ok", True) and not disk.get("unavailable"):
        warning_html = (
            f'<p class="status-panel-alert">Low disk space — below '
            f"{html.escape(str(threshold_mb))} MB threshold</p>"
        )

    restart_html = ""
    if restart_action:
        restart_html = (
            '<div class="status-panel-actions">'
            f'<button type="button" class="btn-restart-server" '
            f'data-restart-action="{html.escape(restart_action)}">'
            "Restart server</button>"
            "</div>"
        )

    return (
        f'<footer class="{panel_class}">'
        '<p class="status-panel-title">Server status</p>'
        f'<div class="status-panel-grid">{"".join(rows)}</div>'
        f"{warning_html}"
        f"{restart_html}"
        "</footer>"
    )


def render_build_toggle_button(project_id: str) -> str:
    pid = html.escape(project_id)
    panel_id = f"build-panel-{pid}"
    return (
        f'<button type="button" class="btn-new-build-toggle" '
        f'aria-expanded="false" aria-controls="{panel_id}">New build</button>'
    )


def _wrap_header_actions(*actions: str) -> str:
    parts = [action for action in actions if action]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f'<div class="project-header-actions">{"".join(parts)}</div>'


def render_build_panel(
    project_id: str,
    *,
    trigger_url: str,
    git_status_url: str,
    git_branches_url: str,
    git_fetch_url: str,
    jobs_url: str,
) -> str:
    pid = html.escape(project_id)
    panel_id = f"build-panel-{pid}"
    return (
        f'<div class="build-panel" id="{panel_id}" hidden data-project-id="{pid}" '
        f'data-trigger-url="{html.escape(trigger_url)}" '
        f'data-git-status-url="{html.escape(git_status_url)}" '
        f'data-git-branches-url="{html.escape(git_branches_url)}" '
        f'data-git-fetch-url="{html.escape(git_fetch_url)}" '
        f'data-jobs-url="{html.escape(jobs_url)}">'
        '<p class="build-git-status build-panel-status muted">Loading git status…</p>'
        '<div class="build-panel-grid">'
        '<div class="build-panel-field">'
        '<label for="branch-' + pid + '">Branch</label>'
        f'<select class="build-branch-select" id="branch-{pid}">'
        '<option value="">(current branch)</option>'
        "</select>"
        "</div>"
        '<div class="build-panel-field">'
        '<label for="mode-' + pid + '">Git mode</label>'
        f'<select class="build-git-mode" id="mode-{pid}">'
        '<option value="auto" selected>Auto</option>'
        '<option value="checkout">Checkout</option>'
        '<option value="stash_checkout">Stash + checkout</option>'
        '<option value="worktree">Worktree</option>'
        "</select>"
        "</div>"
        '<div class="build-panel-field">'
        '<label for="config-' + pid + '">Configuration</label>'
        f'<select class="build-configuration" id="config-{pid}">'
        '<option value="">Default (projects.json)</option>'
        '<option value="Release">Release</option>'
        '<option value="Debug">Debug</option>'
        "</select>"
        "</div>"
        "</div>"
        '<div class="build-panel-actions">'
        '<button type="button" class="btn-build-start">Start build</button>'
        '<button type="button" class="btn-build-secondary btn-build-fetch">Fetch remotes</button>'
        '<button type="button" class="btn-build-secondary btn-build-cancel">Cancel</button>'
        "</div>"
        '<p class="build-panel-progress" aria-live="polite"></p>'
        "</div>"
    )


def _project_icon_build(builds: list[dict]) -> dict | None:
    """Return the most recent build that has an extractable app icon."""
    for build in builds:
        if build.get("has_icon") and build.get("icon_path"):
            return build
    return None


def render_index(
    data: dict,
    base_url: str,
    access_token: str | None = None,
    *,
    enable_delete: bool = True,
    enable_restart: bool = True,
    enable_logout: bool = False,
    enable_build: bool = True,
    ota_dir: Path | None = None,
    server_status: dict | None = None,
    min_disk_mb: int = 5000,
) -> str:
    base = base_url.rstrip("/")
    token = access_token or ""

    def u(url: str) -> str:
        return with_access_token(url, access_token or None)

    logout_html = ""
    if enable_logout:
        logout_html = (
            '<form class="inline" method="post" action="/api/logout">'
            '<button type="submit" class="btn-secondary">Sign out</button>'
            "</form>"
        )

    generated_label = _format_dashboard_timestamp(data.get("generated_at", ""))
    header_actions = (
        f'<div class="page-header-actions">{logout_html}</div>' if logout_html else ""
    )

    sections: list[str] = []
    sections.append(
        f"""<!DOCTYPE html>
<html lang="en">
{base_head("iOS OTA Builds")}
<body>
  <main class="page">
    <header class="page-header">
      <div class="page-header-body">
        <div class="page-header-main">
          <p class="kicker">Builds</p>
          <h1>iOS OTA Builds</h1>
          <p class="muted page-header-meta">Last updated {html.escape(generated_label)}</p>
        </div>
        {header_actions}
      </div>
    </header>
"""
    )

    delete_action = u("/api/builds/delete") if enable_delete and token else ""
    restart_action = u("/api/server/restart") if enable_restart and token else ""
    build_enabled = enable_build and bool(token)
    trigger_url = u("/api/builds/trigger") if build_enabled else ""
    git_status_base = u("/api/git/status") if build_enabled else ""
    git_branches_base = u("/api/git/branches") if build_enabled else ""
    git_fetch_url = u("/api/git/fetch") if build_enabled else ""
    jobs_url = u("/api/builds/jobs") if build_enabled else ""

    def project_api_url(base: str, pid: str) -> str:
        joiner = "&" if "?" in base else "?"
        return f"{base}{joiner}project={html.escape(pid, quote=True)}"

    token_script = ""
    if token:
        token_script = f'<script>window.__OTA_TOKEN={json.dumps(token)};</script>'

    for project_id, project in data.get("projects", {}).items():
        display = html.escape(project.get("display_name", project_id))
        builds = project.get("builds", [])

        build_panel_html = ""
        build_toggle_html = ""
        if build_enabled:
            build_toggle_html = render_build_toggle_button(project_id)
            build_panel_html = render_build_panel(
                project_id,
                trigger_url=trigger_url,
                git_status_url=project_api_url(git_status_base, project_id),
                git_branches_url=project_api_url(git_branches_base, project_id),
                git_fetch_url=git_fetch_url,
                jobs_url=jobs_url,
            )

        if not builds:
            header_actions = _wrap_header_actions(build_toggle_html)
            sections.append(
                f'<section class="project-card">'
                f'<div class="project-card-header"><h2>{display}</h2>{header_actions}</div>'
                f"{build_panel_html}"
                '<p class="empty-state">No builds yet.</p></section>'
            )
            continue

        has_successful = any(b.get("status") == "success" for b in builds)
        header_action_parts: list[str] = []
        if build_toggle_html:
            header_action_parts.append(build_toggle_html)
        if has_successful:
            latest_install_url = u(f"{base}/latest/{project_id}")
            header_action_parts.append(
                _copy_button(
                    latest_install_url,
                    aria_label=f"Copy latest install link for {project.get('display_name', project_id)}",
                    label="Copy latest",
                )
            )
        header_actions = _wrap_header_actions(*header_action_parts)

        project_icon_html = ""
        icon_build = _project_icon_build(builds)
        if icon_build:
            icon_src = u(f"{base}{icon_build['icon_path']}")
            project_icon_html = (
                f'<img class="app-icon" src="{html.escape(icon_src)}" alt="" '
                f'width="40" height="40">'
            )

        title_row = f'<div class="project-title-row">{project_icon_html}<h2>{display}</h2></div>'
        sections.append(
            f'<section class="project-card">'
            f'<div class="project-card-header">{title_row}{header_actions}</div>'
            f"{build_panel_html}"
        )

        sections.append(
            '<div class="table-wrap"><table class="builds-table">'
            f"{_BUILDS_TABLE_COLGROUP}"
            "<thead><tr><th>Build</th><th>Branch</th><th>Commit</th>"
            "<th>Version</th><th>Duration</th><th>Size</th><th>Actions</th></tr></thead><tbody>"
        )
        for b in builds:
            is_failure = b.get("status") == "failure"
            ipa_filename = b.get("ipa_filename") or "app.ipa"
            install = u(b.get("install_url") or f"{base}/{b['path']}/install.html")
            ipa = u(b.get("ipa_url") or f"{base}/{b['path']}/{ipa_filename}")
            log_filename = b.get("log_filename") or "archive.log"
            log_url = u(f"{base}/{b['path']}/{log_filename}")
            diagnostics = u(f"{base}/{b['path']}/diagnostics.md")
            label = html.escape(b.get("build_label") or b.get("dir", ""))
            full_name = html.escape(b.get("ipa_filename") or b.get("dir", ""))
            badges_html = _build_badges(b)
            confirm_msg = "Delete this build permanently?"

            if is_failure:
                actions = _build_failure_actions_menu(
                    diagnostics=diagnostics,
                    log_url=log_url,
                    has_diagnostics=bool(b.get("has_diagnostics")),
                    has_log=bool(b.get("has_log")),
                    delete_action=delete_action,
                    project_id=project_id,
                    build_dir=b.get("dir", ""),
                    confirm_msg=confirm_msg,
                )
            else:
                actions = _build_actions_menu(
                    install=install,
                    ipa=ipa,
                    archive_log=log_url,
                    has_install=bool(b.get("has_install")),
                    has_ipa=bool(b.get("has_ipa")),
                    delete_action=delete_action,
                    project_id=project_id,
                    build_dir=b.get("dir", ""),
                    confirm_msg=confirm_msg,
                )

            build_cell = (
                f'<div class="build-name" title="{full_name}">'
                f'<span class="build-label">{label}</span>{badges_html}'
                f"{_render_build_notes(b)}</div>"
            )

            duration_cell = html.escape(_format_duration(b.get("duration_seconds")))
            size_cell = html.escape(_format_ipa_size(b.get("ipa_size_bytes")))
            row_class = ' class="build-row-failed"' if is_failure else ""

            version_cell = (
                f"{html.escape(str(b.get('version') or '—'))} "
                f"({html.escape(str(b.get('build_number') or '—'))})"
            )

            sections.append(
                f"<tr{row_class}>"
                f"<td>{build_cell}</td>"
                f"{_truncate_table_cell(b.get('branch'), data_label='Branch')}"
                f'<td class="cell-truncate" data-label="Commit">'
                f"{_format_commit_cell(b, project)}</td>"
                f'<td class="cell-nowrap" data-label="Version">{version_cell}</td>'
                f'<td class="meta-cell" data-label="Duration">{duration_cell}</td>'
                f'<td class="meta-cell" data-label="Size">{size_cell}</td>'
                f'<td class="cell-actions">{actions}</td></tr>'
            )
        sections.append("</tbody></table></div></section>")

    panel_status = server_status
    if panel_status is None and ota_dir is not None:
        panel_status = {"disk": collect_disk_stats(ota_dir, min_disk_mb=min_disk_mb)}
    if panel_status is not None:
        sections.append(render_status_panel(panel_status, restart_action=restart_action))

    sections.append(
        f"</main>\n{token_script}\n{_COPY_SCRIPT}\n{_DROPDOWN_SCRIPT}\n{_RESTART_SCRIPT}\n"
        f"{_BUILD_SCRIPT if build_enabled else ''}\n</body></html>"
    )
    return "\n".join(sections)


def load_projects_config(projects_json: Path) -> dict:
    if not projects_json.is_file():
        return {}
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    return config.get("projects", {})
