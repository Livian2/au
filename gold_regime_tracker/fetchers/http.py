"""Shared HTTP helper for the fetchers.

Many of the upstream data hosts (Stooq, the CFTC site) sit behind Cloudflare,
which rejects requests carrying the default ``Python-urllib/3.x`` User-Agent with
an HTTP 403. Sending browser-like headers is the standard remedy. The
User-Agent can be overridden via the ``GRT_USER_AGENT`` environment variable.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def user_agent() -> str:
    return os.environ.get("GRT_USER_AGENT", DEFAULT_USER_AGENT)


def browser_headers(extra: dict | None = None) -> dict:
    headers = {
        "User-Agent": user_agent(),
        "Accept": "text/csv,text/plain,application/octet-stream,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }
    if extra:
        headers.update(extra)
    return headers


class HttpError(RuntimeError):
    """Raised on a failed download. Carries a hint for Cloudflare-style blocks."""


def get(url: str, timeout: int = 30, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers=headers or browser_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code in (403, 503):
            hint = (
                " — this looks like a Cloudflare/bot block. Try setting a custom "
                "GRT_USER_AGENT, or download the file manually and import it."
            )
        raise HttpError(f"HTTP {exc.code} for {url}{hint}") from exc
    except Exception as exc:  # DNS, timeout, network policy, etc.
        raise HttpError(f"Request failed for {url}: {exc}") from exc
