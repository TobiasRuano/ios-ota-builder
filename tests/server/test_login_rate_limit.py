"""Tests for server/login_rate_limit.py."""

from __future__ import annotations

import login_rate_limit as rate_limit_module
import pytest
from login_rate_limit import is_rate_limited, record_failure


@pytest.fixture(autouse=True)
def clear_rate_limits() -> None:
    with rate_limit_module._lock:
        rate_limit_module._failures.clear()
    yield
    with rate_limit_module._lock:
        rate_limit_module._failures.clear()


def test_rate_limit_after_repeated_failures() -> None:
    ip = "203.0.113.10"
    for _ in range(4):
        record_failure(ip)
        assert is_rate_limited(ip) is False
    record_failure(ip)
    assert is_rate_limited(ip) is True
