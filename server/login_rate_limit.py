"""Simple in-memory rate limiting for failed login attempts."""

from __future__ import annotations

import threading
import time

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}


def record_failure(client_ip: str) -> None:
    now = time.time()
    with _lock:
        attempts = _failures.setdefault(client_ip, [])
        attempts.append(now)
        _prune_locked(client_ip, now)


def is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    with _lock:
        _prune_locked(client_ip, now)
        return len(_failures.get(client_ip, [])) >= MAX_ATTEMPTS


def _prune_locked(client_ip: str, now: float) -> None:
    cutoff = now - WINDOW_SECONDS
    attempts = _failures.get(client_ip, [])
    attempts = [ts for ts in attempts if ts >= cutoff]
    if attempts:
        _failures[client_ip] = attempts
    else:
        _failures.pop(client_ip, None)
