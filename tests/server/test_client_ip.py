"""Tests for server/client_ip.py."""

from __future__ import annotations

from types import SimpleNamespace

from client_ip import client_ip_from_request


def _handler(
    *,
    client_address: tuple[str, int] = ("127.0.0.1", 12345),
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    header_map = headers or {}
    return SimpleNamespace(
        client_address=client_address,
        headers=SimpleNamespace(
            get=lambda key, default="": header_map.get(key, default)
        ),
    )


def test_loopback_uses_cf_connecting_ip() -> None:
    handler = _handler(headers={"CF-Connecting-IP": "203.0.113.50"})
    assert client_ip_from_request(handler) == "203.0.113.50"


def test_loopback_without_proxy_headers_returns_loopback() -> None:
    handler = _handler()
    assert client_ip_from_request(handler) == "127.0.0.1"


def test_direct_connection_ignores_spoofed_xff() -> None:
    handler = _handler(
        client_address=("198.51.100.10", 54321),
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    assert client_ip_from_request(handler) == "198.51.100.10"
