# ios-ota-builder

Open-source template to build iOS apps (`.xcodeproj` + SPM), export an **Ad Hoc** IPA, and publish it for **OTA** installation from iPhone.

**Build server:** always-on personal Mac  
**Distribution:** IPA + `manifest.plist` + Cloudflare Tunnel (HTTPS)  
**Without:** Bitrise, GitHub Actions, TestFlight (for fast iteration)

---

## Quick start

```bash
git clone https://github.com/YOUR_USER/ios-ota-builder.git
cd ios-ota-builder
./scripts/setup.sh
```

Then follow the full guide in [`docs/SETUP.md`](docs/SETUP.md).

---

## Architecture

```
Agent / you
    │
    ▼
agent_build_ota.sh <project-id>
    │
    ├─► xcodebuild (resolve SPM → archive → export Ad Hoc)
    │
    ├─► OTA-Builds/<project>/<build>/  (IPA, manifest, install.html)
    │
    └─► Local server :8765 (Python)
            │
            ▼
        cloudflared tunnel
            │
            ▼
        https://ota.yourdomain.com  ──► Safari on iPhone
```

The pipeline **does not modify source code** — it only builds and publishes.

---

## Requirements

| Component | Notes |
|------------|-------|
| macOS | Always-on Mac |
| Xcode | Apple Developer account signed in |
| `jq`, `python3`, `git` | Preinstalled or via Homebrew |
| `cloudflared` | `brew install cloudflared` |
| Cloudflare domain | e.g. `ota.yourdomain.com` |
| Registered iPhone | UDID in Apple Developer (Ad Hoc) |

Supported apps: `.xcodeproj`, Swift Package Manager, **no** CocoaPods or `.xcworkspace`.

---

## Daily usage

```bash
# Release (default in projects.json)
./agent_build_ota.sh my-app

# Debug — faster iteration
./agent_build_ota.sh --debug my-app
```

**Important:** the argument is the **`project-id`**, not the repo path.

```bash
# ✅ Correct
./agent_build_ota.sh my-app

# ❌ Incorrect
./agent_build_ota.sh ~/Developer/my-app
```

Get install link (latest build for a project):

```bash
./scripts/print_install_url.sh my-app
```

View **all** builds (dashboard with Install / IPA / logs per project):

```bash
./scripts/print_dashboard_url.sh
```

Open that URL in your browser and bookmark it. Without `?token=...` the entire server responds **401**.

---

## Configuration

| File | Committed | Description |
|---------|------------|-------------|
| `config/local.env.example` | Yes | Secrets and globals template |
| `config/local.env` | **No** (gitignored) | Your URL, token, team ID, tunnel |
| `config/projects.json.example` | Yes | Example app |
| `config/projects.json` | **No** (gitignored) | Your real apps |
| `config/env.sh` | Yes | Generic loader (no secrets) |

Main variables in `config/local.env`:

| Variable | Description |
|----------|-------------|
| `OTA_BASE_URL` | Public HTTPS URL |
| `OTA_ACCESS_TOKEN` | OTA server access token |
| `APPLE_TEAM_ID` | Apple Developer team ID |
| `OTA_HOSTNAME` | Cloudflare tunnel hostname |
| `CLOUDFLARE_TUNNEL_ID` | Tunnel UUID |

`team_id` per project in `projects.json` is optional — inherits `APPLE_TEAM_ID` if missing.

---

## Authentication and dashboard

The OTA server is **fully** behind a shared token:

- Without `?token=...` → **401** on any route.
- With token → dynamic dashboard at `/` with all builds (Install, IPA, Log, **Delete**).

After each build, stdout JSON includes:

- `install_url` — to install on iPhone (Safari).
- `dashboard_url` — to browse, download, or delete past builds (bookmark once).

No terminal needed: the agent returns both links in chat.

---

## Build retention

Defaults (`config/local.env`):

| Variable | Default | Effect |
|----------|---------|--------|
| `OTA_KEEP_BUILDS` | `5` | Maximum builds per project |
| `OTA_MAX_AGE_DAYS` | `7` | Deletes older builds |

Runs at the end of each build and **daily at 03:00** (LaunchAgent `ota-cleanup`).

After each build, `work/` (DerivedData, `.xcarchive`, export staging) is deleted. Retained per build: IPA, `icon.png`, `install.html`, `manifest.plist`, `summary.json`, and logs. Cleanup also strips any leftover `work/` from builds still kept by retention.

The dashboard reflects disk state instantly: manual deletion in Finder or **Delete** button on the web.

---

## Background services

```bash
./scripts/install_launchagents.sh
./server/restart_server.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cloudflared.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cleanup.plist
```

---

## AI agents

Instructions: [`docs/AGENT_INSTRUCTIONS.md`](docs/AGENT_INSTRUCTIONS.md)

1. **Never** run `xcodebuild` directly
2. Use `agent_build_ota.sh <project-id>`
3. On failure: read `diagnostics.md`, fix code, retry (max 3)
4. Return `install_url` and `dashboard_url` to the user

---

## Roadmap

Planned improvements and detailed specs: [`docs/roadmap.md`](docs/roadmap.md) · [`docs/roadmap-features.md`](docs/roadmap-features.md)

---

## Pre-publication audit

Before pushing to a public repo:

```bash
./scripts/audit-public-safe.sh
```

---

## Repository structure

```
ios-ota-builder/
├── agent_build_ota.sh
├── config/
│   ├── env.sh
│   ├── local.env.example
│   └── projects.json.example
├── scripts/
│   ├── setup.sh
│   ├── audit-public-safe.sh
│   └── ...
├── server/
│   └── cloudflared/config.yml.template
├── launchd/*.plist.template
└── docs/
    ├── SETUP.md
    ├── AGENT_INSTRUCTIONS.md
    ├── roadmap.md
    └── roadmap-features.md
```

---

## License

MIT — see [`LICENSE`](LICENSE).
