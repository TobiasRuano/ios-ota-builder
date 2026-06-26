#!/usr/bin/env bash
# Pre-push audit: ensure no private config is staged or tracked.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0

log_ok() { printf '  OK  %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*"; FAIL=1; }

echo "=== audit-public-safe ==="

# Staged private files
for f in config/local.env config/projects.json config/access.token; do
  if git diff --cached --name-only 2>/dev/null | grep -qx "$f"; then
    log_fail "Staged private file: $f"
  fi
done

# Staged build artifacts
for pattern in OTA-Builds .server; do
  if git diff --cached --name-only 2>/dev/null | grep -q "^${pattern}"; then
    log_fail "Staged build artifact path: $pattern"
  fi
done

# Personal patterns in tracked files (index + working tree tracked)
PATTERN='tobiasruano|7344G4M3BL|d667c1cd|cfa1289|trotos\.|ruano\.t10@'
if git grep -iE "$PATTERN" -- ':!scripts/audit-public-safe.sh' 2>/dev/null; then
  log_fail "Personal/sensitive pattern found in tracked files (see above)"
else
  log_ok "No personal patterns in tracked files"
fi

# Forbidden committed paths
for f in config/projects.json server/cloudflared/config.yml; do
  if git ls-files --error-unmatch "$f" &>/dev/null; then
    log_fail "Private file still tracked by git: $f"
  fi
done

for f in config/local.env.example config/projects.json.example; do
  if [[ -f "$f" ]]; then
    log_ok "Template present: $f"
  else
    log_fail "Missing template: $f"
  fi
done

# Spanish text in tracked prose files (docs and config examples)
SPANISH_PATTERN='[áéíóúñüÁÉÍÓÚÑÜ¿¡]|\b(Editá|Abrí|Seguí|Anotá|Tocá|podés|rotás|necesitás|descargalos|cargá|guardala|Plantilla|Guía|Configuración|Descripción|Inicio rápido)\b'
SPANISH_LOCALE="${AUDIT_SPANISH_LOCALE:-en_US.UTF-8}"
if LC_ALL="$SPANISH_LOCALE" LANG="$SPANISH_LOCALE" git grep -iE "$SPANISH_PATTERN" -- '*.md' '*.example' 2>/dev/null; then
  log_fail "Spanish text detected in tracked files (see above)"
else
  log_ok "No Spanish text in tracked docs"
fi

if [[ $FAIL -ne 0 ]]; then
  echo ""
  echo "Audit failed. Fix issues before making the repository public."
  exit 1
fi

echo ""
echo "Audit passed."
