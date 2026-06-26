"""URL helpers for OTA access tokens."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def with_access_token(url: str, token: str | None) -> str:
    if not token:
        return url
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["token"] = [token]
    query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=query))
