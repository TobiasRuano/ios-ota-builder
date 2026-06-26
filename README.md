# ios-ota-builder

Plantilla open source para compilar apps iOS (`.xcodeproj` + SPM), exportar un IPA **Ad Hoc** y publicarlo para instalación **OTA** desde el iPhone.

**Build server:** Mac personal siempre encendida  
**Distribución:** IPA + `manifest.plist` + Cloudflare Tunnel (HTTPS)  
**Sin:** Bitrise, GitHub Actions, TestFlight (para iteración rápida)

---

## Inicio rápido

```bash
git clone https://github.com/YOUR_USER/ios-ota-builder.git
cd ios-ota-builder
./scripts/setup.sh
```

Luego seguí la guía completa en [`docs/SETUP.md`](docs/SETUP.md).

---

## Arquitectura

```
Agente / vos
    │
    ▼
agent_build_ota.sh <project-id>
    │
    ├─► xcodebuild (resolve SPM → archive → export Ad Hoc)
    │
    ├─► OTA-Builds/<project>/<build>/  (IPA, manifest, install.html)
    │
    └─► Servidor local :8765 (Python)
            │
            ▼
        cloudflared tunnel
            │
            ▼
        https://ota.yourdomain.com  ──► Safari en iPhone
```

El pipeline **no modifica código** — solo compila y publica.

---

## Requisitos

| Componente | Notas |
|------------|-------|
| macOS | Mac siempre encendida |
| Xcode | Cuenta Apple Developer logueada |
| `jq`, `python3`, `git` | Preinstalados o vía Homebrew |
| `cloudflared` | `brew install cloudflared` |
| Dominio en Cloudflare | Ej. `ota.yourdomain.com` |
| iPhone registrado | UDID en Apple Developer (Ad Hoc) |

Apps soportadas: `.xcodeproj`, Swift Package Manager, **sin** CocoaPods ni `.xcworkspace`.

---

## Uso diario

```bash
# Release (default en projects.json)
./agent_build_ota.sh my-app

# Debug — iteración más rápida
./agent_build_ota.sh --debug my-app
```

**Importante:** el argumento es el **`project-id`**, no la ruta del repo.

```bash
# ✅ Correcto
./agent_build_ota.sh my-app

# ❌ Incorrecto
./agent_build_ota.sh ~/Developer/my-app
```

Obtener link de install (último build de un proyecto):

```bash
./scripts/print_install_url.sh my-app
```

Ver **todos** los builds (dashboard con Install / IPA / logs por proyecto):

```bash
./scripts/print_dashboard_url.sh
```

Abrí esa URL en el navegador y guardala como bookmark. Sin `?token=...` todo el servidor responde **401**.

---

## Configuración

| Archivo | Commiteado | Descripción |
|---------|------------|-------------|
| `config/local.env.example` | Sí | Plantilla de secretos y globals |
| `config/local.env` | **No** (gitignored) | Tu URL, token, team ID, tunnel |
| `config/projects.json.example` | Sí | App de ejemplo |
| `config/projects.json` | **No** (gitignored) | Tus apps reales |
| `config/env.sh` | Sí | Loader genérico (sin secretos) |

Variables principales en `config/local.env`:

| Variable | Descripción |
|----------|-------------|
| `OTA_BASE_URL` | URL pública HTTPS |
| `OTA_ACCESS_TOKEN` | Token de acceso al servidor OTA |
| `APPLE_TEAM_ID` | Team ID de Apple Developer |
| `OTA_HOSTNAME` | Hostname del tunnel Cloudflare |
| `CLOUDFLARE_TUNNEL_ID` | UUID del tunnel |

`team_id` por proyecto en `projects.json` es opcional — hereda `APPLE_TEAM_ID` si falta.

---

## Autenticación y dashboard

El servidor OTA está **completamente** detrás de un token compartido:

- Sin `?token=...` → **401** en cualquier ruta.
- Con token → dashboard dinámico en `/` con todos los builds (Install, IPA, Log, **Delete**).

Tras cada build, el JSON de stdout incluye:

- `install_url` — para instalar en iPhone (Safari).
- `dashboard_url` — para ver, descargar o borrar builds pasados (bookmark una vez).

No hace falta terminal: el agente devuelve ambos links en el chat.

---

## Retención de builds

Por defecto (`config/local.env`):

| Variable | Default | Efecto |
|----------|---------|--------|
| `OTA_KEEP_BUILDS` | `5` | Máximo de builds por proyecto |
| `OTA_MAX_AGE_DAYS` | `7` | Borra builds más viejos |

Se ejecuta al final de cada build y **diariamente a las 03:00** (LaunchAgent `ota-cleanup`).

El dashboard refleja el disco al instante: borrado manual en Finder o botón **Delete** en la web.

---

## Servicios en background

```bash
./scripts/install_launchagents.sh
./server/restart_server.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cloudflared.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cleanup.plist
```

---

## Agentes de IA

Instrucciones: [`docs/AGENT_INSTRUCTIONS.md`](docs/AGENT_INSTRUCTIONS.md)

1. **Nunca** ejecutar `xcodebuild` directo
2. Usar `agent_build_ota.sh <project-id>`
3. Si falla: leer `diagnostics.md`, corregir código, reintentar (máx. 3)
4. Devolver `install_url` y `dashboard_url` al usuario

---

## Auditoría pre-publicación

Antes de hacer push a un repo público:

```bash
./scripts/audit-public-safe.sh
```

---

## Estructura del repo

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
    └── AGENT_INSTRUCTIONS.md
```

---

## Licencia

MIT — ver [`LICENSE`](LICENSE).
