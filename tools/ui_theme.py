"""Shared CSS design tokens and HTML helpers for OTA web pages."""

from __future__ import annotations

import html

THEME_COLOR = "#f7f9fc"
FONT_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap"
)


def css_reset_and_tokens() -> str:
    return """
:root {
  color-scheme: light;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  --background: #f7f9fc;
  --surface: #ffffff;
  --surface-muted: #f8fafc;
  --text: #172033;
  --muted: #68748a;
  --border: #ccd4e0;
  --border-strong: #aeb9ca;
  --border-subtle: #dce2eb;
  --accent: #3568d4;
  --success: #378564;
  --status-active: #5ebc93;
  --danger: #c94a4a;
  --focus: #3568d4;
}

*, *::before, *::after { box-sizing: border-box; }

body {
  min-width: 320px;
  margin: 0;
  background: var(--background);
  color: var(--text);
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5;
}

a {
  color: inherit;
  text-decoration-thickness: .08em;
  text-underline-offset: .2em;
  -webkit-tap-highlight-color: transparent;
}

:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 4px;
}

@media (prefers-reduced-motion: reduce) {
  * { transition-duration: .01ms !important; }
}
"""


def css_layout(*, narrow: bool = False) -> str:
    max_width = "480px" if narrow else "960px"
    return f"""
.page {{
  width: min(100% - 3rem, {max_width});
  margin: 0 auto;
  padding: clamp(1.5rem, 4vw, 2.5rem) 0;
}}

@media (max-width: 720px) {{
  .page {{ width: min(100% - 2rem, {max_width}); }}
}}
"""


def css_labels() -> str:
    return """
.kicker {
  margin: 0 0 .5rem;
  color: var(--accent);
  font: 500 .82rem "IBM Plex Mono", monospace;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.muted {
  margin: 0;
  color: var(--muted);
  font-size: .9rem;
}

.page h1 {
  margin: 0 0 .35rem;
  font-size: clamp(1.75rem, 4vw, 2.25rem);
  font-weight: 600;
  letter-spacing: -.03em;
  line-height: 1.15;
}

.page-header {
  margin-bottom: 2rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-strong);
}

.empty-state {
  margin: 0;
  padding: 1.25rem 1.5rem;
  color: var(--muted);
  background: var(--surface-muted);
  border-radius: 6px;
  font-size: .9rem;
}
"""


def css_buttons() -> str:
    return """
.btn-primary,
.btn-danger {
  display: inline-block;
  padding: .4rem .85rem;
  border: none;
  border-radius: 6px;
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
  font-size: .85rem;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
}

.btn-primary:hover { background: #2d57b8; color: #fff; }

.btn-danger {
  background: var(--danger);
  color: #fff;
}

.btn-danger:hover { background: #a83d3d; }

.btn-primary.block {
  display: block;
  width: 100%;
  padding: 1rem;
  border-radius: 10px;
  font-size: 1.05rem;
  text-align: center;
}

.link-accent {
  color: var(--accent);
  font-weight: 500;
  text-decoration: none;
}

.link-accent:hover { text-decoration: underline; }

form.inline { display: inline; margin: 0; }

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
  align-items: center;
}

@media (max-width: 720px) {
  .actions { flex-direction: column; align-items: flex-start; }
}
"""


def css_cards() -> str:
    return """
.project-card {
  margin-bottom: 1.5rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  overflow: hidden;
}

.project-card h2 {
  margin: 0;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 1.15rem;
  font-weight: 600;
  letter-spacing: -.02em;
}

.install-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  padding: 1.75rem 1.5rem;
}

.install-card h1 {
  margin: 0 0 .75rem;
  font-size: 1.5rem;
  font-weight: 600;
  letter-spacing: -.03em;
}

.install-qr {
  display: none;
  margin: 0 0 1.25rem;
  text-align: center;
}

.install-qr svg {
  display: block;
  width: min(200px, 100%);
  height: auto;
  margin: 0 auto .5rem;
}

@media (min-width: 600px) {
  .install-qr { display: block; }
}
"""


def css_table() -> str:
    return """
.table-wrap { overflow-x: auto; }

table.builds-table {
  width: 100%;
  border-collapse: collapse;
  font-size: .9rem;
}

table.builds-table th {
  padding: .65rem 1.25rem;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-muted);
  color: var(--muted);
  font: 500 .72rem "IBM Plex Mono", monospace;
  letter-spacing: .08em;
  text-align: left;
  text-transform: uppercase;
  white-space: nowrap;
}

table.builds-table td {
  padding: .75rem 1.25rem;
  border-bottom: 1px solid var(--border-subtle);
  vertical-align: top;
}

table.builds-table tbody tr:last-child td { border-bottom: none; }

table.builds-table tbody tr:hover td { background: var(--surface-muted); }

.build-name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .5rem;
  font-weight: 500;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: .35rem;
  color: var(--success);
  font: 500 .72rem "IBM Plex Mono", monospace;
  letter-spacing: .04em;
  text-transform: uppercase;
}

.status-dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--status-active);
}
"""


def css_all(*, narrow: bool = False) -> str:
    return "\n".join(
        [
            css_reset_and_tokens(),
            css_layout(narrow=narrow),
            css_labels(),
            css_buttons(),
            css_cards(),
            css_table(),
        ]
    )


def base_head(title: str, *, narrow: bool = False) -> str:
    safe_title = html.escape(title)
    return f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta name="theme-color" content="{THEME_COLOR}">
  <title>{safe_title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="{FONT_URL}" rel="stylesheet">
  <style>
{css_all(narrow=narrow)}
  </style>
</head>"""


def unauthorized_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
{base_head("401 Unauthorized")}
<body>
  <main class="page">
    <header class="page-header">
      <p class="kicker">Access</p>
      <h1>401 Unauthorized</h1>
      <p class="muted">Access requires a valid token.</p>
    </header>
  </main>
</body>
</html>
"""
