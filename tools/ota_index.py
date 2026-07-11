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

    fetch(action, {
      method: "POST",
      credentials: "same-origin",
      headers: window.__OTA_AUTH_MODE === "session" && window.__OTA_CSRF
        ? { "X-CSRF-Token": window.__OTA_CSRF }
        : {}
    })
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

_BUILD_SCRIPT_BODY = """
  function setStatus(panel, text, isWarn) {
    var el = panel.querySelector(".build-git-status");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("warn", !!isWarn);
  }

  function setWorkspaceDetail(panel, html, isWarn) {
    var el = panel.querySelector(".git-workspace-detail");
    if (!el) return;
    el.innerHTML = html;
    el.classList.toggle("warn", !!isWarn);
  }

  function setProgress(panel, text, active) {
    var el = panel.querySelector(".build-panel-progress");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("is-active", !!active);
  }

  function syncStatusLabel(status) {
    var map = {
      in_sync: "In sync",
      behind: "Behind remote",
      ahead: "Ahead of remote",
      diverged: "Diverged",
      unknown: "Unknown"
    };
    return map[status] || status || "Unknown";
  }

  function syncStatusClass(status) {
    if (status === "in_sync") return "git-sync-ok";
    if (status === "behind") return "git-sync-warn";
    if (status === "ahead" || status === "diverged") return "git-sync-danger";
    return "git-sync-muted";
  }

  function findProjectPanels(projectId) {
    return {
      build: document.getElementById("build-panel-" + projectId),
      workspace: document.getElementById("git-workspace-panel-" + projectId)
    };
  }

  function getGitParamsFromPanel(panel) {
    return {
      branch: ((panel.querySelector(".git-branch-select") || {}).value || ""),
      gitMode: ((panel.querySelector(".git-mode-select") || {}).value || "auto"),
      syncStrategy: ((panel.querySelector(".git-sync-strategy") || {}).value || "match_remote")
    };
  }

  function syncGitFields(sourcePanel) {
    var projectId = sourcePanel.getAttribute("data-project-id");
    if (!projectId) return;
    var panels = findProjectPanels(projectId);
    var params = getGitParamsFromPanel(sourcePanel);
    [panels.build, panels.workspace].forEach(function (target) {
      if (!target || target === sourcePanel) return;
      var branchSel = target.querySelector(".git-branch-select");
      var modeSel = target.querySelector(".git-mode-select");
      var stratSel = target.querySelector(".git-sync-strategy");
      if (branchSel && branchSel.value !== params.branch) branchSel.value = params.branch;
      if (modeSel && modeSel.value !== params.gitMode) modeSel.value = params.gitMode;
      if (stratSel && stratSel.value !== params.syncStrategy) stratSel.value = params.syncStrategy;
    });
  }

  function workspaceQuery(panel) {
    var params = getGitParamsFromPanel(panel);
    return "branch=" + encodeURIComponent(params.branch)
      + "&git_mode=" + encodeURIComponent(params.gitMode)
      + "&strategy=" + encodeURIComponent(params.syncStrategy);
  }

  function renderPreflightResults(panel, data) {
    var el = panel.querySelector(".build-preflight-results");
    if (!el || !data) return;
    var checks = data.checks || [];
    var status = data.status || "unknown";
    var duration = data.duration_seconds != null ? data.duration_seconds + "s" : "";
    var summary = "Environment: " + status;
    if (duration) summary += " (" + duration + ")";
    var html = '<p class="build-preflight-summary">' + escapeHtml(summary) + "</p><ul>";
    checks.forEach(function (check) {
      var name = check.name || "check";
      var st = check.status || "unknown";
      var cls = "preflight-ok";
      if (st === "warn") cls = "preflight-warn";
      if (st === "failed") cls = "preflight-failed";
      var line = '<li class="' + cls + '"><span class="preflight-name">' + escapeHtml(name) + "</span>";
      line += ' <span class="preflight-status">' + escapeHtml(st) + "</span>";
      if (check.free_mb != null && check.threshold_mb != null) {
        line += ' <span class="preflight-meta">'
          + escapeHtml(check.free_mb + " MB free (min " + check.threshold_mb + " MB)")
          + "</span>";
      }
      if (check.reachable === true || check.reachable === false) {
        line += ' <span class="preflight-meta">'
          + escapeHtml(check.reachable ? "reachable" : "not reachable")
          + "</span>";
      }
      if (check.message) {
        line += ' <span class="preflight-message">' + escapeHtml(check.message) + "</span>";
      }
      line += "</li>";
      html += line;
    });
    html += "</ul>";
    el.innerHTML = html;
    el.hidden = false;
  }

  var BUILDS_TABLE_HTML = '<table class="builds-table"><colgroup>'
    + '<col class="col-build"><col class="col-branch"><col class="col-commit">'
    + '<col class="col-version"><col class="col-duration"><col class="col-size"><col class="col-actions">'
    + '</colgroup><thead><tr><th>Build</th><th>Branch</th><th>Commit</th>'
    + '<th>Version</th><th>Duration</th><th>Size</th><th>Actions</th></tr></thead></table>';

  function escapeHtml(text) {
    var d = document.createElement("div");
    d.textContent = text == null ? "" : String(text);
    return d.innerHTML;
  }

  function findProjectCard(panel) {
    return panel ? panel.closest(".project-card") : null;
  }

  function ensureBuildsTable(card) {
    if (!card) return null;
    var wrap = card.querySelector(".table-wrap");
    if (wrap) return wrap.querySelector("table.builds-table");
    var empty = card.querySelector(".empty-state");
    if (empty) empty.remove();
    wrap = document.createElement("div");
    wrap.className = "table-wrap";
    wrap.innerHTML = BUILDS_TABLE_HTML;
    card.appendChild(wrap);
    return wrap.querySelector("table.builds-table");
  }

  function findBuildRow(card, jobId) {
    if (!card || !jobId) return null;
    return card.querySelector('tr.build-row-in-progress[data-job-id="' + jobId + '"]');
  }

  function insertBuildRow(panel, job) {
    var card = findProjectCard(panel);
    var table = ensureBuildsTable(card);
    if (!table || !job || !job.id) return;
    if (findBuildRow(card, job.id)) return;
    var branch = job.branch || "—";
    var config = job.configuration || "";
    var configBadge = config
      ? '<span class="status-badge">' + escapeHtml(config) + "</span>"
      : "";
    var pct = job.progress_pct != null ? job.progress_pct : 5;
    var label = job.stage_label || "Starting…";
    var row = document.createElement("tr");
    row.className = "build-row-in-progress";
    row.setAttribute("data-job-id", job.id);
    row.innerHTML =
      '<td data-label="Build"><div class="build-name">'
      + '<span class="build-label">Building…</span>'
      + '<div class="badge-group"><span class="status-badge badge-in-progress">in progress</span>'
      + configBadge + "</div>"
      + '<div class="build-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="'
      + pct + '"><div class="build-progress-bar" style="width:' + pct + '%"></div></div>'
      + '<span class="build-progress-label">' + escapeHtml(label) + "</span>"
      + "</div></td>"
      + '<td class="cell-truncate" data-label="Branch">' + escapeHtml(branch) + "</td>"
      + '<td class="cell-truncate" data-label="Commit">—</td>'
      + '<td class="cell-nowrap" data-label="Version">—</td>'
      + '<td class="meta-cell" data-label="Duration">—</td>'
      + '<td class="meta-cell" data-label="Size">—</td>'
      + '<td class="cell-actions">—</td>';
    var tbody = document.createElement("tbody");
    tbody.className = "build-entry build-entry-in-progress";
    tbody.appendChild(row);
    var firstEntry = table.querySelector("tbody");
    if (firstEntry) {
      table.insertBefore(tbody, firstEntry);
    } else {
      table.appendChild(tbody);
    }
  }

  function updateBuildRow(panel, job) {
    var card = findProjectCard(panel);
    if (!job || !job.id) return;
    var row = findBuildRow(card, job.id);
    if (!row) {
      insertBuildRow(panel, job);
      row = findBuildRow(card, job.id);
    }
    if (!row) return;
    var pct = job.progress_pct != null ? job.progress_pct : 5;
    var label = job.stage_label || job.stage || job.status || "Building…";
    var bar = row.querySelector(".build-progress-bar");
    var progress = row.querySelector(".build-progress");
    var labelEl = row.querySelector(".build-progress-label");
    if (bar) {
      bar.style.width = pct + "%";
      bar.classList.toggle(
        "is-active",
        job.stage === "archiving" || job.stage === "exporting" || job.stage === "resolving_spm"
      );
    }
    if (progress) progress.setAttribute("aria-valuenow", String(pct));
    if (labelEl) labelEl.textContent = label;
  }

  function markBuildRowFailed(panel, job) {
    var card = findProjectCard(panel);
    var row = findBuildRow(card, job && job.id);
    if (!row) return;
    row.classList.remove("build-row-in-progress");
    row.classList.add("build-row-failed");
    var entry = row.closest("tbody");
    if (entry) {
      entry.classList.remove("build-entry-in-progress");
      entry.classList.add("build-entry-failed");
    }
    var badgeGroup = row.querySelector(".badge-group");
    if (badgeGroup) {
      var html = '<span class="status-badge badge-failed">failed</span>';
      if (job.stage_label || job.stage) {
        html += '<span class="status-badge badge-failed-stage">@ '
          + escapeHtml(job.stage_label || job.stage) + "</span>";
      }
      badgeGroup.innerHTML = html;
    }
    var labelEl = row.querySelector(".build-progress-label");
    if (labelEl) {
      labelEl.textContent = job.error
        || ("Failed at " + (job.stage_label || job.stage || "unknown"));
      labelEl.classList.add("build-progress-error");
    }
    var progress = row.querySelector(".build-progress");
    if (progress) progress.remove();
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
    return card ? card.querySelector(".build-panel, .git-workspace-panel") : null;
  }

  function findToggleForPanel(panel) {
    var panelId = panel.id;
    if (!panelId) return null;
    var card = panel.closest(".project-card");
    if (!card) return null;
    return card.querySelector('[aria-controls="' + panelId + '"]');
  }

  function openPanel(panel) {
    panel.hidden = false;
    var toggle = findToggleForPanel(panel);
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    if (!panel.dataset.statusLoaded) {
      loadWorkspaceStatus(panel);
    }
  }

  function closePanel(panel) {
    panel.hidden = true;
    var toggle = findToggleForPanel(panel);
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  }

  function togglePanel(panel) {
    if (panel.hidden) {
      openPanel(panel);
    } else {
      closePanel(panel);
    }
  }

  function openBuildPanel(panel) { openPanel(panel); }
  function closeBuildPanel(panel) { closePanel(panel); }
  function toggleBuildPanel(panel) { togglePanel(panel); }

  function renderWorkspaceDetail(data) {
    var ws = data.build_workspace || {};
    var remote = data.remote || {};
    var status = data.sync_status || "unknown";
    var statusCls = syncStatusClass(status);
    var lines = [
      '<div class="git-workspace-grid">',
      '<div><span class="git-workspace-label">Build workspace</span>',
      '<code class="git-workspace-path">' + escapeHtml(ws.path || "—") + "</code></div>",
      '<div><span class="git-workspace-label">Workspace HEAD</span>',
      '<span>' + escapeHtml((ws.branch || "?") + " @ " + (ws.commit || "unknown")) + "</span></div>",
      '<div><span class="git-workspace-label">Remote (' + escapeHtml(remote.name || "origin") + ")</span>",
      '<span>' + escapeHtml((remote.branch || "?") + " @ " + (remote.commit || "unknown")) + "</span>",
      (remote.subject ? ' <span class="git-workspace-subject">' + escapeHtml(remote.subject) + "</span>" : ""),
      "</div>",
      '<div><span class="git-workspace-label">Sync status</span>',
      '<span class="' + statusCls + '">' + escapeHtml(syncStatusLabel(status)) + "</span>",
      (data.commits_behind ? ' <span class="git-sync-meta">(' + data.commits_behind + " behind)</span>" : ""),
      (data.commits_ahead ? ' <span class="git-sync-meta">(' + data.commits_ahead + " ahead)</span>" : ""),
      "</div>"
    ];
    if (data.last_sync && data.last_sync.at) {
      lines.push(
        '<div><span class="git-workspace-label">Last sync</span>',
        '<span>' + escapeHtml(data.last_sync.at + " → " + (data.last_sync.to_commit || "").slice(0, 7)) + "</span></div>"
      );
    }
    if (data.last_build_commit && data.last_build_commit.commit) {
      lines.push(
        '<div><span class="git-workspace-label">Last build</span>',
        '<span>' + escapeHtml(data.last_build_commit.commit) + "</span></div>"
      );
    }
    if (remote.fetched_at) {
      lines.push(
        '<div><span class="git-workspace-label">Last fetch</span>',
        '<span>' + escapeHtml(remote.fetched_at) + "</span></div>"
      );
    }
    lines.push("</div>");
    return lines.join("");
  }

  function buildSummaryFromWorkspace(data) {
    var ws = data.build_workspace || {};
    var remote = data.remote || {};
    var status = data.sync_status || "unknown";
    var parts = ["Will build: " + (ws.branch || "?") + " @ " + (ws.commit || "unknown")];
    parts.push(syncStatusLabel(status));
    if (status !== "in_sync" && remote.commit) {
      parts.push("remote @ " + remote.commit);
    }
    return parts.join(" · ");
  }

  function loadWorkspaceStatus(panel) {
    var projectId = panel.getAttribute("data-project-id");
    var workspaceUrl = panel.getAttribute("data-git-workspace-url");
    if (!workspaceUrl) return;
    var url = apiUrl(workspaceUrl) + (workspaceUrl.indexOf("?") >= 0 ? "&" : "?") + workspaceQuery(panel);
    fetch(url, fetchOpts())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          setStatus(panel, data.error, true);
          setWorkspaceDetail(panel, "<p>" + escapeHtml(data.error) + "</p>", true);
          return;
        }
        panel.dataset.statusLoaded = "1";
        panel.dataset.syncStatus = data.sync_status || "unknown";
        var isWarn = data.sync_status === "behind" || data.sync_status === "diverged"
          || (data.build_workspace && data.build_workspace.dirty_count > 0)
          || data.base_repo && data.base_repo.has_conflicts;
        if (panel.classList.contains("build-panel")) {
          setStatus(panel, buildSummaryFromWorkspace(data), isWarn);
        }
        if (panel.classList.contains("git-workspace-panel")) {
          setWorkspaceDetail(panel, renderWorkspaceDetail(data), isWarn);
        }
        var panels = findProjectPanels(projectId);
        if (panels.build && panels.build !== panel) {
          setStatus(panels.build, buildSummaryFromWorkspace(data), isWarn);
        }
        if (panels.workspace && panels.workspace !== panel) {
          setWorkspaceDetail(panels.workspace, renderWorkspaceDetail(data), isWarn);
        }

        var select = panel.querySelector(".git-branch-select");
        if (select && !select.dataset.loaded) {
          select.dataset.loaded = "1";
          var branchesUrl = panel.getAttribute("data-git-branches-url");
          if (branchesUrl) {
            fetch(apiUrl(branchesUrl), fetchOpts())
              .then(function (r) { return r.json(); })
              .then(function (br) {
                fillBranchSelect(select, br, data.branch || br.current);
              })
              .catch(function () {});
          }
        }

        var stratSel = panel.querySelector(".git-sync-strategy");
        if (stratSel && data.sync_strategy && !stratSel.dataset.userSet) {
          stratSel.value = data.sync_strategy;
        }

        var startBtn = panel.querySelector(".btn-build-start");
        if (startBtn) {
          startBtn.disabled = !!(data.base_repo && data.base_repo.has_conflicts) || !!data.active_job;
        }
        if (data.active_job && data.active_job.id && panels.build) {
          insertBuildRow(panels.build, data.active_job);
          pollJob(panels.build, data.active_job.id);
        }
      })
      .catch(function () {
        setStatus(panel, "Could not load git workspace status", true);
      });
  }

  function loadGitStatus(panel) {
    loadWorkspaceStatus(panel);
  }

  function pollJob(panel, jobId) {
    var jobsUrl = panel.getAttribute("data-jobs-url");
    if (!jobsUrl) return;
    var jobUrl = jobsUrl.replace(/\\/?$/, "") + "/" + encodeURIComponent(jobId);
    setProgress(panel, "Build in progress…", true);
    insertBuildRow(panel, { id: jobId, progress_pct: 5, stage_label: "Starting…" });
    var startBtn = panel.querySelector(".btn-build-start");
    if (startBtn) startBtn.disabled = true;

    function check() {
      fetch(apiUrl(jobUrl), fetchOpts())
        .then(function (r) { return r.json(); })
        .then(function (job) {
          if (!job || job.error) return;
          var st = job.status || "";
          if (st === "queued" || st === "preparing" || st === "building") {
            var msg = job.stage_label || ("Build " + st + "…");
            setProgress(panel, msg, true);
            updateBuildRow(panel, job);
            setTimeout(check, POLL_MS);
            return;
          }
          if (st === "success") {
            setProgress(panel, "Build succeeded — refreshing…", false);
            updateBuildRow(panel, Object.assign({}, job, { progress_pct: 100, stage_label: "Complete" }));
            setTimeout(function () { window.location.reload(); }, 1200);
            return;
          }
          markBuildRowFailed(panel, job);
          setProgress(
            panel,
            job.error || ("Failed at " + (job.stage_label || job.stage || "unknown")),
            true
          );
          setTimeout(function () { window.location.reload(); }, 1200);
        })
        .catch(function () {
          setTimeout(check, POLL_MS);
        });
    }
    check();
  }

  document.querySelectorAll(".build-panel, .git-workspace-panel").forEach(function (panel) {
    var workspaceUrl = panel.getAttribute("data-git-workspace-url");
    if (!workspaceUrl) return;
    fetch(apiUrl(workspaceUrl), fetchOpts())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.active_job && data.active_job.id) {
          var buildPanel = findProjectPanels(panel.getAttribute("data-project-id")).build;
          if (buildPanel) openBuildPanel(buildPanel);
        }
      })
      .catch(function () {});
  });

  document.addEventListener("change", function (e) {
    var field = e.target.closest(".git-branch-select, .git-mode-select, .git-sync-strategy");
    if (!field) return;
    var panel = field.closest(".build-panel, .git-workspace-panel");
    if (!panel) return;
    if (field.classList.contains("git-sync-strategy")) {
      field.dataset.userSet = "1";
    }
    syncGitFields(panel);
    panel.dataset.statusLoaded = "";
    var panels = findProjectPanels(panel.getAttribute("data-project-id"));
    if (panels.build) panels.build.dataset.statusLoaded = "";
    if (panels.workspace) panels.workspace.dataset.statusLoaded = "";
    loadWorkspaceStatus(panel);
  });

  document.addEventListener("click", function (e) {
    var toggleBtn = e.target.closest(".btn-new-build-toggle, .btn-git-workspace-toggle");
    if (toggleBtn) {
      var panelToToggle = findPanelForToggle(toggleBtn);
      if (panelToToggle) togglePanel(panelToToggle);
      return;
    }

    var cancelBtn = e.target.closest(".btn-build-cancel, .btn-git-workspace-cancel");
    if (cancelBtn) {
      var cancelPanel = cancelBtn.closest(".build-panel, .git-workspace-panel");
      if (cancelPanel) closePanel(cancelPanel);
      return;
    }

    var fetchBtn = e.target.closest(".btn-build-fetch, .btn-git-fetch");
    if (fetchBtn) {
      var panel = fetchBtn.closest(".build-panel, .git-workspace-panel");
      var url = panel.getAttribute("data-git-fetch-url");
      fetchBtn.disabled = true;
      fetch(apiUrl(url), postFetchOptions(
        "project_id=" + encodeURIComponent(panel.getAttribute("data-project-id"))
      ))
        .then(function (r) { return r.json(); })
        .then(function () {
          panel.querySelectorAll(".git-branch-select").forEach(function (select) {
            select.dataset.loaded = "";
          });
          panel.dataset.statusLoaded = "";
          loadWorkspaceStatus(panel);
        })
        .finally(function () { fetchBtn.disabled = false; });
      return;
    }

    var syncBtn = e.target.closest(".btn-git-sync");
    if (syncBtn) {
      var syncPanel = syncBtn.closest(".git-workspace-panel, .build-panel");
      if (!syncPanel) return;
      var syncUrl = syncPanel.getAttribute("data-git-sync-url");
      if (!syncUrl) return;
      var params = getGitParamsFromPanel(syncPanel);
      syncBtn.disabled = true;
      var body = "project_id=" + encodeURIComponent(syncPanel.getAttribute("data-project-id"))
        + "&branch=" + encodeURIComponent(params.branch)
        + "&git_mode=" + encodeURIComponent(params.gitMode)
        + "&strategy=" + encodeURIComponent(params.syncStrategy);
      fetch(apiUrl(syncUrl), postFetchOptions(body))
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok || !res.j.ok) {
            throw new Error((res.j && res.j.error) || "sync failed");
          }
          syncPanel.dataset.statusLoaded = "";
          loadWorkspaceStatus(syncPanel);
          setProgress(syncPanel, "Workspace synced to " + ((res.j.after && res.j.after.commit) || "latest"), false);
        })
        .catch(function (err) {
          setProgress(syncPanel, err.message || "Git sync failed", true);
        })
        .finally(function () { syncBtn.disabled = false; });
      return;
    }

    var preflightBtn = e.target.closest(".btn-build-preflight");
    if (preflightBtn) {
      var preflightPanel = preflightBtn.closest(".build-panel");
      var preflightUrl = preflightPanel.getAttribute("data-preflight-url");
      if (!preflightUrl) return;
      var originalText = preflightBtn.textContent;
      preflightBtn.disabled = true;
      preflightBtn.textContent = "Checking…";
      var preflightBody = "project_id=" + encodeURIComponent(
        preflightPanel.getAttribute("data-project-id")
      );
      fetch(apiUrl(preflightUrl), postFetchOptions(preflightBody))
        .then(function (r) {
          return r.json().then(function (j) { return { status: r.status, j: j }; });
        })
        .then(function (res) {
          if (res.status === 200 || res.status === 422) {
            if (!res.j || !res.j.checks) {
              throw new Error("invalid preflight response");
            }
            renderPreflightResults(preflightPanel, res.j);
            return;
          }
          throw new Error((res.j && res.j.error) || "preflight failed");
        })
        .catch(function (err) {
          setProgress(preflightPanel, err.message || "Could not check environment", true);
        })
        .finally(function () {
          preflightBtn.disabled = false;
          preflightBtn.textContent = originalText;
        });
      return;
    }

    var startBtn = e.target.closest(".btn-build-start");
    if (!startBtn || startBtn.disabled) return;
    var panel = startBtn.closest(".build-panel");
    var triggerUrl = panel.getAttribute("data-trigger-url");
    var params = getGitParamsFromPanel(panel);
    var config = (panel.querySelector(".build-configuration") || {}).value || "";
    var syncStatus = panel.dataset.syncStatus || "unknown";

    function triggerBuild(allowStale) {
      var body = "project_id=" + encodeURIComponent(panel.getAttribute("data-project-id"))
        + "&branch=" + encodeURIComponent(params.branch)
        + "&git_mode=" + encodeURIComponent(params.gitMode)
        + "&sync_strategy=" + encodeURIComponent(params.syncStrategy)
        + "&configuration=" + encodeURIComponent(config)
        + "&sync_before_build=true"
        + "&allow_stale_build=" + (allowStale ? "true" : "false");
      startBtn.disabled = true;
      fetch(apiUrl(triggerUrl), postFetchOptions(body))
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
    }

    if (syncStatus === "behind" || syncStatus === "diverged") {
      var msg = "Workspace is " + syncStatus + " relative to remote. Sync & build is recommended.";
      if (window.confirm(msg + "\\n\\nOK = Sync happens automatically during build.\\nCancel = abort.")) {
        triggerBuild(false);
      }
      return;
    }
    triggerBuild(false);
  });
})();
"""

_BUILD_SCRIPT_SESSION = (
    """<script>
(function () {
  var POLL_MS = 4000;

  function apiUrl(path) {
    return path;
  }

  function fetchOpts() {
    return { credentials: "same-origin" };
  }

  function postFetchOptions(body) {
    var opts = {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }
    };
    if (body !== undefined) {
      body += "&csrf_token=" + encodeURIComponent(window.__OTA_CSRF || "");
      opts.body = body;
    }
    return opts;
  }
"""
    + _BUILD_SCRIPT_BODY
    + "</script>"
)

_BUILD_SCRIPT_TOKEN = (
    """<script>
(function () {
  var POLL_MS = 4000;

  function apiUrl(path) {
    return path + (path.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(window.__OTA_TOKEN || "");
  }

  function fetchOpts() {
    return {};
  }

  function postFetchOptions(body) {
    var opts = {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }
    };
    if (body !== undefined) {
      opts.body = body;
    }
    return opts;
  }
"""
    + _BUILD_SCRIPT_BODY
    + "</script>"
)

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
    ranked_projects: list[tuple[str, dict, tuple[float, int]]] = []

    for project_id, meta in projects_config.items():
        project_dir = ota_dir / project_id
        builds: list[dict] = []
        top_key: tuple[float, int] = (float("-inf"), 0)
        if project_dir.is_dir():
            ranked: list[tuple[dict, tuple[float, int]]] = []
            for build_dir in project_dir.iterdir():
                entry = _build_entry_if_valid(build_dir, project_id)
                if entry is not None:
                    ranked.append((entry, _build_sort_key(entry, build_dir)))
            ranked.sort(key=lambda item: item[1], reverse=True)
            builds = [entry for entry, _ in ranked]
            if ranked:
                top_key = ranked[0][1]

        latest_marked = False
        for entry in builds:
            if not latest_marked and entry.get("status") == "success":
                entry["is_latest"] = True
                latest_marked = True

        ranked_projects.append(
            (
                project_id,
                {
                    "display_name": meta.get("display_name", project_id),
                    "repo_url": meta.get("repo_url"),
                    "repo_type": meta.get("repo_type", "github"),
                    "builds": builds,
                },
                top_key,
            )
        )

    ranked_projects.sort(key=lambda item: item[2], reverse=True)
    result["projects"] = {pid: data for pid, data, _ in ranked_projects}
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


def _csrf_hidden_input(csrf_token: str | None) -> str:
    if not csrf_token:
        return ""
    return f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">'


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
    csrf_token: str | None = None,
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
            f"{_csrf_hidden_input(csrf_token)}"
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
    csrf_token: str | None = None,
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
            f"{_csrf_hidden_input(csrf_token)}"
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
        stage = build.get("stage")
        if stage:
            badges.append(
                f'<span class="status-badge badge-failed-stage">@ {html.escape(str(stage))}</span>'
            )
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


def render_git_workspace_toggle_button(project_id: str) -> str:
    pid = html.escape(project_id)
    panel_id = f"git-workspace-panel-{pid}"
    return (
        f'<button type="button" class="btn-git-workspace-toggle" '
        f'aria-expanded="false" aria-controls="{panel_id}">Git workspace</button>'
    )


def _git_sync_strategy_options(selected: str = "match_remote") -> str:
    options = [
        ("match_remote", "Match remote exactly"),
        ("fast_forward", "Fast-forward only"),
        ("recreate_worktree", "Recreate worktree"),
    ]
    parts: list[str] = []
    for value, label in options:
        sel = " selected" if value == selected else ""
        parts.append(f'<option value="{value}"{sel}>{html.escape(label)}</option>')
    return "".join(parts)


def _git_panel_fields(project_id: str, *, id_prefix: str) -> str:
    pid = html.escape(project_id)
    return (
        '<div class="build-panel-grid">'
        '<div class="build-panel-field">'
        f'<label for="{id_prefix}-branch-{pid}">Branch</label>'
        f'<select class="git-branch-select" id="{id_prefix}-branch-{pid}">'
        '<option value="">(current branch)</option>'
        "</select>"
        "</div>"
        '<div class="build-panel-field">'
        f'<label for="{id_prefix}-mode-{pid}">Git mode</label>'
        f'<select class="git-mode-select" id="{id_prefix}-mode-{pid}">'
        '<option value="auto" selected>Auto</option>'
        '<option value="checkout">Checkout</option>'
        '<option value="stash_checkout">Stash + checkout</option>'
        '<option value="worktree">Worktree</option>'
        "</select>"
        "</div>"
        '<div class="build-panel-field">'
        f'<label for="{id_prefix}-strategy-{pid}">Sync strategy</label>'
        f'<select class="git-sync-strategy" id="{id_prefix}-strategy-{pid}">'
        f"{_git_sync_strategy_options()}"
        "</select>"
        "</div>"
        "</div>"
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
    preflight_url: str,
    git_workspace_url: str,
    git_branches_url: str,
    git_fetch_url: str,
    git_sync_url: str,
    jobs_url: str,
) -> str:
    pid = html.escape(project_id)
    panel_id = f"build-panel-{pid}"
    return (
        f'<div class="build-panel" id="{panel_id}" hidden data-project-id="{pid}" '
        f'data-trigger-url="{html.escape(trigger_url)}" '
        f'data-preflight-url="{html.escape(preflight_url)}" '
        f'data-git-workspace-url="{html.escape(git_workspace_url)}" '
        f'data-git-branches-url="{html.escape(git_branches_url)}" '
        f'data-git-fetch-url="{html.escape(git_fetch_url)}" '
        f'data-git-sync-url="{html.escape(git_sync_url)}" '
        f'data-jobs-url="{html.escape(jobs_url)}">'
        '<p class="build-panel-title">New build</p>'
        '<p class="build-git-status build-panel-status muted">Loading workspace status…</p>'
        f"{_git_panel_fields(project_id, id_prefix='build')}"
        '<div class="build-panel-field">'
        f'<label for="config-{pid}">Configuration</label>'
        f'<select class="build-configuration" id="config-{pid}">'
        '<option value="">Default (projects.json)</option>'
        '<option value="Release">Release</option>'
        '<option value="Debug">Debug</option>'
        "</select>"
        "</div>"
        '<div class="build-panel-actions">'
        '<button type="button" class="btn-build-secondary btn-build-preflight">Check environment</button>'
        '<button type="button" class="btn-build-start">Start build</button>'
        '<button type="button" class="btn-build-secondary btn-build-fetch" '
        'title="Refresh remote branch list (does not update build workspace)">Fetch remotes</button>'
        '<button type="button" class="btn-build-secondary btn-git-sync">Sync workspace</button>'
        '<button type="button" class="btn-build-secondary btn-build-cancel">Cancel</button>'
        "</div>"
        '<div class="build-preflight-results" hidden aria-live="polite"></div>'
        '<p class="build-panel-progress" aria-live="polite"></p>'
        "</div>"
    )


def render_git_workspace_panel(
    project_id: str,
    *,
    git_workspace_url: str,
    git_branches_url: str,
    git_fetch_url: str,
    git_sync_url: str,
) -> str:
    pid = html.escape(project_id)
    panel_id = f"git-workspace-panel-{pid}"
    return (
        f'<div class="git-workspace-panel build-panel" id="{panel_id}" hidden data-project-id="{pid}" '
        f'data-git-workspace-url="{html.escape(git_workspace_url)}" '
        f'data-git-branches-url="{html.escape(git_branches_url)}" '
        f'data-git-fetch-url="{html.escape(git_fetch_url)}" '
        f'data-git-sync-url="{html.escape(git_sync_url)}">'
        '<p class="build-panel-title">Git workspace</p>'
        '<p class="build-git-status build-panel-status muted">Loading workspace status…</p>'
        f"{_git_panel_fields(project_id, id_prefix='ws')}"
        '<div class="git-workspace-detail build-panel-status muted">'
        "Loading workspace details…"
        "</div>"
        '<div class="build-panel-actions">'
        '<button type="button" class="btn-build-secondary btn-git-fetch" '
        'title="Refresh remote branch list (does not update build workspace)">Fetch remotes</button>'
        '<button type="button" class="btn-build-secondary btn-git-sync">Sync workspace</button>'
        '<button type="button" class="btn-build-secondary btn-git-workspace-cancel">Close</button>'
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
    auth_mode: str = "token",
    csrf_token: str | None = None,
    enable_delete: bool = True,
    enable_restart: bool = True,
    enable_logout: bool = False,
    enable_build: bool = True,
    ota_dir: Path | None = None,
    server_status: dict | None = None,
    min_disk_mb: int = 5000,
) -> str:
    base = base_url.rstrip("/")
    use_token_urls = auth_mode == "token" and bool(access_token)
    dashboard_enabled = auth_mode in ("session", "token")

    def u(url: str) -> str:
        if use_token_urls:
            return with_access_token(url, access_token)
        return url

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

    delete_action = u("/api/builds/delete") if enable_delete and dashboard_enabled else ""
    restart_action = u("/api/server/restart") if enable_restart and dashboard_enabled else ""
    build_enabled = enable_build and dashboard_enabled
    trigger_url = u("/api/builds/trigger") if build_enabled else ""
    preflight_url = u("/api/builds/preflight") if build_enabled else ""
    git_status_base = u("/api/git/status") if build_enabled else ""
    git_branches_base = u("/api/git/branches") if build_enabled else ""
    git_workspace_base = u("/api/git/workspace") if build_enabled else ""
    git_fetch_url = u("/api/git/fetch") if build_enabled else ""
    git_sync_url = u("/api/git/sync") if build_enabled else ""
    jobs_url = u("/api/builds/jobs") if build_enabled else ""

    def project_api_url(base: str, pid: str) -> str:
        joiner = "&" if "?" in base else "?"
        return f"{base}{joiner}project={html.escape(pid, quote=True)}"

    auth_script = ""
    if auth_mode == "token" and access_token:
        auth_script = (
            f'<script>window.__OTA_AUTH_MODE="token";'
            f"window.__OTA_TOKEN={json.dumps(access_token)};</script>"
        )
    elif auth_mode == "session" and csrf_token:
        auth_script = (
            f'<script>window.__OTA_AUTH_MODE="session";'
            f"window.__OTA_CSRF={json.dumps(csrf_token)};</script>"
        )

    for project_id, project in data.get("projects", {}).items():
        display = html.escape(project.get("display_name", project_id))
        builds = project.get("builds", [])

        build_panel_html = ""
        git_workspace_panel_html = ""
        build_toggle_html = ""
        git_workspace_toggle_html = ""
        if build_enabled:
            build_toggle_html = render_build_toggle_button(project_id)
            git_workspace_toggle_html = render_git_workspace_toggle_button(project_id)
            build_panel_html = render_build_panel(
                project_id,
                trigger_url=trigger_url,
                preflight_url=preflight_url,
                git_workspace_url=project_api_url(git_workspace_base, project_id),
                git_branches_url=project_api_url(git_branches_base, project_id),
                git_fetch_url=git_fetch_url,
                git_sync_url=git_sync_url,
                jobs_url=jobs_url,
            )
            git_workspace_panel_html = render_git_workspace_panel(
                project_id,
                git_workspace_url=project_api_url(git_workspace_base, project_id),
                git_branches_url=project_api_url(git_branches_base, project_id),
                git_fetch_url=git_fetch_url,
                git_sync_url=git_sync_url,
            )

        if not builds:
            header_actions = _wrap_header_actions(build_toggle_html, git_workspace_toggle_html)
            sections.append(
                f'<section class="project-card">'
                f'<div class="project-card-header"><h2>{display}</h2>{header_actions}</div>'
                f"{build_panel_html}{git_workspace_panel_html}"
                '<p class="empty-state">No builds yet.</p></section>'
            )
            continue

        has_successful = any(b.get("status") == "success" for b in builds)
        header_action_parts: list[str] = []
        if build_toggle_html:
            header_action_parts.append(build_toggle_html)
        if git_workspace_toggle_html:
            header_action_parts.append(git_workspace_toggle_html)
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
            f"{build_panel_html}{git_workspace_panel_html}"
        )

        sections.append(
            '<div class="table-wrap"><table class="builds-table">'
            f"{_BUILDS_TABLE_COLGROUP}"
            "<thead><tr><th>Build</th><th>Branch</th><th>Commit</th>"
            "<th>Version</th><th>Duration</th><th>Size</th><th>Actions</th></tr></thead>"
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
                    csrf_token=csrf_token,
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
                    csrf_token=csrf_token,
                )

            build_cell = (
                f'<div class="build-name" title="{full_name}">'
                f'<span class="build-label">{label}</span>{badges_html}</div>'
            )
            notes_html = _render_build_notes(b)

            duration_cell = html.escape(_format_duration(b.get("duration_seconds")))
            size_cell = html.escape(_format_ipa_size(b.get("ipa_size_bytes")))
            row_class = ' class="build-row-failed"' if is_failure else ""

            version_cell = (
                f"{html.escape(str(b.get('version') or '—'))} "
                f"({html.escape(str(b.get('build_number') or '—'))})"
            )

            entry_class = "build-entry"
            if is_failure:
                entry_class += " build-entry-failed"

            sections.append(f'<tbody class="{entry_class}">')
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
            if notes_html:
                sections.append(
                    f'<tr class="build-notes-row">'
                    f'<td colspan="7">{notes_html}</td></tr>'
                )
            sections.append("</tbody>")
        sections.append("</table></div></section>")

    panel_status = server_status
    if panel_status is None and ota_dir is not None:
        panel_status = {"disk": collect_disk_stats(ota_dir, min_disk_mb=min_disk_mb)}
    if panel_status is not None:
        sections.append(render_status_panel(panel_status, restart_action=restart_action))

    sections.append(
        f"</main>\n{auth_script}\n{_COPY_SCRIPT}\n{_DROPDOWN_SCRIPT}\n{_RESTART_SCRIPT}\n"
        f"{_BUILD_SCRIPT_SESSION if auth_mode == 'session' else _BUILD_SCRIPT_TOKEN if build_enabled else ''}\n</body></html>"
    )
    return "\n".join(sections)


def load_projects_config(projects_json: Path) -> dict:
    if not projects_json.is_file():
        return {}
    config = json.loads(projects_json.read_text(encoding="utf-8"))
    return config.get("projects", {})
