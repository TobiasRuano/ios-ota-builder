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

Obtener link de install:

```bash
./scripts/print_install_url.sh my-app
```

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

## Autenticación

- El servidor OTA requiere token en query (`?token=...`) o header `Authorization: Bearer <token>`.
- Sin token → **401 Unauthorized**.
- Compartí solo los `install_url` generados por el pipeline (incluyen el token).
- Rotar token: `./scripts/generate_access_token.sh` y `./server/restart_server.sh`.

---

## Servicios en background

```bash
./scripts/install_launchagents.sh
./server/restart_server.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cloudflared.plist
```

---

## Agentes de IA

Instrucciones: [`docs/AGENT_INSTRUCTIONS.md`](docs/AGENT_INSTRUCTIONS.md)

1. **Nunca** ejecutar `xcodebuild` directo
2. Usar `agent_build_ota.sh <project-id>`
3. Si falla: leer `diagnostics.md`, corregir código, reintentar (máx. 3)
4. Devolver `install_url` al usuario

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
