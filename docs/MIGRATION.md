# Migration — setup existente a config local

Guía para operadores que ya tenían el pipeline antes de la plantilla pública.

---

## Qué cambió

| Antes | Ahora |
|-------|-------|
| `config/access.token` | `OTA_ACCESS_TOKEN` en `config/local.env` |
| `OTA_BASE_URL` en `env.sh` | `config/local.env` |
| `config/projects.json` commiteado | Gitignored; ejemplo en `.example` |
| `server/cloudflared/config.yml` en repo | Template + render a `~/.cloudflared/` |
| `launchd/*.plist` (paths personales) | Templates + `install_launchagents.sh` |
| `config/ExportOptions.adhoc.plist` | Template + generación en runtime |

---

## Migración automática

```bash
./scripts/setup.sh
```

Detecta valores legacy de:

- `config/access.token` → `OTA_ACCESS_TOKEN`
- `config/projects.json` → `APPLE_TEAM_ID`
- `server/cloudflared/config.yml` o `~/.cloudflared/config.yml` → hostname y tunnel ID
- `config/ExportOptions.adhoc.plist` → `APPLE_TEAM_ID` (fallback)

Tu `config/projects.json` existente **no se sobrescribe**.

---

## Después de migrar

```bash
./server/setup_cloudflared.sh
./scripts/install_launchagents.sh
./server/restart_server.sh
./scripts/verify_signing.sh <project-id>
```

Si usabas LaunchAgents viejos con labels personalizados, descargalos antes de instalar los nuevos:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<old-label>.ota-server.plist 2>/dev/null || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<old-label>.ota-cloudflared.plist 2>/dev/null || true
```

Luego cargá los nuevos con `install_launchagents.sh`.

---

## Publicar repo limpio

```bash
./scripts/audit-public-safe.sh
git checkout --orphan public-main
git add -A
git commit -m "Initial public template"
git branch -D main && git branch -m main
```

Rotá el token después de publicar: `./scripts/generate_access_token.sh`
