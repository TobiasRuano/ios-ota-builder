#!/usr/bin/env python3
"""Set OTA admin password hash in config/local.env."""

from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from credentials import (  # noqa: E402
    DEFAULT_ADMIN_USERNAME,
    PasswordValidationError,
    hash_password,
    validate_password_strength,
)

LOCAL_ENV = ROOT / "config" / "local.env"


def upsert_env_line(lines: list[str], key: str, value: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(key)}=")
    replaced = False
    out: list[str] = []
    for line in lines:
        if pattern.match(line):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    return out


def main() -> int:
    if not LOCAL_ENV.is_file():
        print(f"Missing {LOCAL_ENV} — run ./scripts/setup.sh first", file=sys.stderr)
        return 1

    username = input(f"Admin username [{DEFAULT_ADMIN_USERNAME}]: ").strip() or DEFAULT_ADMIN_USERNAME
    password = getpass.getpass("New admin password: ")
    confirm = getpass.getpass("Confirm password: ")
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        return 1
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        validate_password_strength(password)
    except PasswordValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    password_hash = hash_password(password)
    lines = LOCAL_ENV.read_text(encoding="utf-8").splitlines()
    lines = upsert_env_line(lines, "OTA_ADMIN_USERNAME", username)
    lines = upsert_env_line(lines, "OTA_ADMIN_PASSWORD_HASH", f"'{password_hash}'")
    LOCAL_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOCAL_ENV.chmod(0o600)

    print(f"Updated admin credentials in {LOCAL_ENV}")
    print(f"Restart server (required to apply and invalidate sessions): {ROOT}/server/restart_server.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
