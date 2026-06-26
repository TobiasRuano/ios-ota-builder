"""Resolve client IP for rate limiting behind a local reverse proxy."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler


def _is_loopback(address: str) -> bool:
    if address == "::1":
        return True
    if address.startswith("::ffff:"):
        address = address.rsplit(":", 1)[-1]
    return address == "127.0.0.1"


def client_ip_from_request(handler: BaseHTTPRequestHandler) -> str:
    """Return the best-effort client IP for rate limiting."""
    remote = handler.client_address[0]
    if not _is_loopback(remote):
        return remote

    for header in ("CF-Connecting-IP", "True-Client-IP"):
        value = handler.headers.get(header, "").strip()
        if value:
            return value.split(",")[0].strip()

    return remote
