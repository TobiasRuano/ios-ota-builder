# Setup guide — ios-ota-builder

Guía paso a paso para personalizar la plantilla en tu Mac.

---

## 1. Clonar e inicializar

```bash
git clone https://github.com/YOUR_USER/ios-ota-builder.git
cd ios-ota-builder
./scripts/setup.sh
```

`setup.sh` crea:

- `config/local.env` (modo `600`, gitignored)
- `config/projects.json` desde el ejemplo (si no existe)

Editá `config/local.env` con tus valores:

```bash
OTA_BASE_URL=https://ota.yourdomain.com
OTA_ACCESS_TOKEN=<generado por setup.sh o generate_access_token.sh>
APPLE_TEAM_ID=XXXXXXXXXX
OTA_HOSTNAME=ota.yourdomain.com
CLOUDFLARE_TUNNEL_NAME=ios-ota
CLOUDFLARE_TUNNEL_ID=your-tunnel-uuid
```

---

## 2. Registrar tus apps

```bash
cp config/projects.json.example config/projects.json   # si setup.sh no lo creó
```

Editá `config/projects.json`:

```json
{
  "projects": {
    "my-app": {
      "display_name": "My App",
      "path": "/Users/YOU/Developer/my-app",
      "xcodeproj": "MyApp.xcodeproj",
      "scheme": "MyApp",
      "configuration": "Release",
      "bundle_id": "com.example.myapp"
    }
  }
}
```

`team_id` es opcional si `APPLE_TEAM_ID` está en `local.env`.

Listar IDs:

```bash
jq -r '.projects | keys[]' config/projects.json
```

---

## 3. Cloudflare Tunnel

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create ios-ota
```

Anotá el tunnel UUID en `config/local.env` → `CLOUDFLARE_TUNNEL_ID`.

Renderizar config en `~/.cloudflared/`:

```bash
./server/setup_cloudflared.sh
cloudflared tunnel route dns ios-ota ota.yourdomain.com
```

---

## 4. Firmado Ad Hoc (Apple)

1. Registrar **UDID del iPhone** en [developer.apple.com → Devices](https://developer.apple.com/account/resources/devices/list)
2. Xcode → **Settings → Accounts** → tu team → **Download Manual Profiles**
3. Si falla el export: **Manage Certificates → + Apple Distribution**

Preflight:

```bash
./scripts/verify_signing.sh my-app
```

---

## 5. Servicios en background

```bash
./scripts/install_launchagents.sh
./server/restart_server.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cloudflared.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ios-ota-builder.ota-cleanup.plist
```

Verificar:

```bash
source config/env.sh
curl -I "https://ota.yourdomain.com/"                              # → 401 sin token
curl -I "https://ota.yourdomain.com/?token=$OTA_ACCESS_TOKEN"    # → 200
```

---

## 6. Retención y dashboard

Variables en `config/local.env`:

```bash
OTA_KEEP_BUILDS=5      # máximo por proyecto
OTA_MAX_AGE_DAYS=7     # antigüedad máxima
```

- Limpieza automática al final de cada build y diaria a las 03:00 (`ota-cleanup` LaunchAgent).
- El dashboard (`dashboard_url` en el JSON del build) lista solo builds con IPA en disco.
- Botón **Delete** en cada fila: borra del disco y desaparece del listado (funciona desde iPhone).

Forzar limpieza manual:

```bash
./scripts/cleanup_ota.sh
```

---

## 7. Symlink opcional

```bash
mkdir -p ~/bin
ln -sf "$(pwd)/agent_build_ota.sh" ~/bin/agent_build_ota
```

---

## 8. Primer build

```bash
./agent_build_ota.sh my-app
```

El JSON de salida incluye `install_url` y `dashboard_url` — no hace falta correr scripts extra.

---

## Instalar en iPhone

1. Abrí el `install_url` en **Safari** (no Chrome)
2. Tocá **Install App**
3. Si no abre: **Ajustes → General → VPN y gestión de dispositivos** → confiar en el desarrollador

El iPhone debe tener su UDID registrado en el perfil Ad Hoc.

---

## Troubleshooting

| Problema | Solución |
|----------|----------|
| `Missing config/local.env` | `./scripts/setup.sh` |
| Unknown project-id | Usar `my-app`, no la ruta del repo |
| `401` en OTA | Token incorrecto → `restart_server.sh` |
| `502` en Cloudflare | Servidor local caído + tunnel activo |
| Export/signing failed | `verify_signing.sh`; UDID; certificado Distribution |

Logs de fallo: `OTA-Builds/<project>/<build>/diagnostics.md`

---

## Rotar token

```bash
./scripts/generate_access_token.sh
./server/restart_server.sh
```

El token **no expira solo**. Es un secreto fijo en `config/local.env` hasta que lo rotés manualmente con `./scripts/generate_access_token.sh`. Podés guardar el `dashboard_url` en favoritos sin problema.

Solo deja de funcionar si rotás el token (entonces necesitás el nuevo link del agente o `./scripts/print_dashboard_url.sh`).
