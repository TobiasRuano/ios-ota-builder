# Agent Instructions — iOS OTA Pipeline

You are building an iOS app that will be installed over-the-air (Ad Hoc) on an iPhone.

## Rules

1. **Never run `xcodebuild` directly.** Always use the pipeline entry point.
2. **Pass `project-id`, never a repo path.** The pipeline resolves paths from `config/projects.json`.
3. **The pipeline does not modify the iOS app repo.** You fix code in the app project; the pipeline builds and publishes. When `auto_increment_build` is enabled for a project in `config/projects.json`, the pipeline assigns the next `CFBundleVersion` via an `xcodebuild` override (counter stored in `config/build_counters.json`).
4. **Maximum 3 build attempts** per task. After each failure, read `diagnostics.md` in the build output folder.
5. **Return `install_url`, `latest_install_url`, and `dashboard_url`** from the JSON output when the build succeeds.
   - `install_url` — for the user to install **this** build on iPhone (Safari).
   - `latest_install_url` — stable bookmark (`/latest/<project-id>`) that always redirects to the newest successful build.
   - `dashboard_url` — to browse, download, or delete past builds (bookmark once).
6. **After modifying Python in `server/` or `tools/`, run unit tests before finishing.** Use `./scripts/run_tests.sh` (works on Linux and macOS). Fix any failures before committing or handing off.

## Build command

**Argument = `project-id` only** (short slug registered in `config/projects.json`).

```bash
# Correct
/path/to/ios-ota-builder/agent_build_ota.sh my-app
/path/to/ios-ota-builder/agent_build_ota.sh --debug my-app

# Wrong — do NOT pass the app repo path
/path/to/ios-ota-builder/agent_build_ota.sh ~/Developer/my-app
```

List registered project IDs:

```bash
jq -r '.projects | keys[]' /path/to/ios-ota-builder/config/projects.json
```

### Flags

```bash
agent_build_ota.sh --debug my-app    # fast iteration
agent_build_ota.sh --release my-app  # force Release
```

## Workflow

```
Modify code
    ↓
If Python changed in server/ or tools/ → ./scripts/run_tests.sh
    ↓
agent_build_ota.sh <project-id>
    ↓
Parse JSON stdout
    ↓
If status == "failure" → read diagnostics.md → fix code → retry (max 3)
    ↓
Return install_url + dashboard_url to user
```

## Unit tests

Python logic in `server/` and `tools/` has automated unit tests. Run them after any change to those directories:

```bash
/path/to/ios-ota-builder/scripts/run_tests.sh
```

- Works on **Linux** (Cursor Cloud) and **macOS** — no Xcode required.
- Installs `pytest` from `requirements-dev.txt` on first run.
- Full iOS pipeline validation (`agent_build_ota.sh`) still requires your Mac with Xcode.

Stable install URL for bookmarks:

```bash
/path/to/ios-ota-builder/scripts/print_install_url.sh --latest my-app
```

## Success output (JSON)

```json
{
  "status": "success",
  "project": "my-app",
  "branch": "main",
  "commit": "abc1234",
  "duration_seconds": 312,
  "install_url": "https://ota.example.com/my-app/25-06-142/install.html?token=...",
  "latest_install_url": "https://ota.example.com/latest/my-app?token=...",
  "dashboard_url": "https://ota.example.com/?token=...",
  "manifest_url": "https://...",
  "ipa_url": "https://...",
  "version": "1.2.0",
  "build_number": "42"
}
```

- `install_url` points at **this** build folder.
- `latest_install_url` is a stable redirect (`GET /latest/<project-id>`) to the newest successful build — safe to bookmark for agents and testers.

When `auto_increment_build` is enabled, `build_number` reflects the overridden `CFBundleVersion` for that OTA build.

## Failure output

On failure, check:

- `OTA-Builds/<project-id>/<build-dir>/diagnostics.md` — human-readable diagnosis
- `archive.log` / `export.log` — full xcodebuild output
- `summary.json` — structured metadata with `stage` field

Common fixes:

| Stage | Fix |
|-------|-----|
| `environment` / unknown project-id | Use `project-id` (e.g. `my-app`), not repo path |
| `environment` | Run `verify_signing.sh`; ensure Apple account in Xcode |
| `signing` / `export` | Register iPhone UDID; create Apple Distribution cert |
| `dependencies` | Fix SPM packages or network |
| `archive` | Fix compile errors in source code |

## Preflight (optional)

```bash
/path/to/ios-ota-builder/scripts/verify_signing.sh my-app
/path/to/ios-ota-builder/scripts/serve_check.sh
```

## Installing on iPhone

1. Open `install_url` in **Safari** (not Chrome).
2. Tap **Install App**.
3. Settings → General → VPN & Device Management → trust developer if prompted.

The iPhone UDID must be registered in the Ad Hoc provisioning profile.

## Configuration

- Private secrets: `config/local.env` (see `./scripts/setup.sh`)
- App registry: `config/projects.json` (copy from `projects.json.example`)
- Per-project build counters: `config/build_counters.json` (created automatically when `auto_increment_build` is enabled). The next build number is **reserved during `resolve`** (after SPM resolution), not after publish.
- `auto_increment_build` requires integer `CFBundleVersion` values (e.g. `42`, not `201.4`). Non-integer build numbers cause the pipeline to fail with a clear error.

**Important:** `install_url` and `dashboard_url` include the access token. Treat them like passwords.
