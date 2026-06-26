# Migration — existing setup to local config

Guide for operators who already had the pipeline before the public template.

---

## What changed

| Before | Now |
|-------|-------|
| `config/access.token` | `OTA_ACCESS_TOKEN` in `config/local.env` |
| `OTA_BASE_URL` in `env.sh` | `config/local.env` |
| `config/projects.json` committed | Gitignored; example in `.example` |
| `server/cloudflared/config.yml` in repo | Template + render to `~/.cloudflared/` |
| `launchd/*.plist` (personal paths) | Templates + `install_launchagents.sh` |
| `config/ExportOptions.adhoc.plist` | Template + runtime generation |

---

## Automatic migration

```bash
./scripts/setup.sh
```

Detects legacy values from:

- `config/access.token` → `OTA_ACCESS_TOKEN`
- `config/projects.json` → `APPLE_TEAM_ID`
- `server/cloudflared/config.yml` or `~/.cloudflared/config.yml` → hostname and tunnel ID
- `config/ExportOptions.adhoc.plist` → `APPLE_TEAM_ID` (fallback)

Your existing `config/projects.json` is **not overwritten**.

---

## After migrating

```bash
./server/setup_cloudflared.sh
./scripts/install_launchagents.sh
./server/restart_server.sh
./scripts/verify_signing.sh <project-id>
```

If you used old LaunchAgents with custom labels, unload them before installing the new ones:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<old-label>.ota-server.plist 2>/dev/null || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<old-label>.ota-cloudflared.plist 2>/dev/null || true
```

Then load the new ones with `install_launchagents.sh`.

---

## Publish a clean repo

```bash
./scripts/audit-public-safe.sh
git checkout --orphan public-main
git add -A
git commit -m "Initial public template"
git branch -D main && git branch -m main
```

Rotate the token after publishing: `./scripts/generate_access_token.sh`
