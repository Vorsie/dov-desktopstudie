"""Minimal HTTP client on urllib: GET with timeout, retry on 5xx/network errors, optional disk
cache keyed by the full URL. The fetch function is injectable for tests."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

USER_AGENT = "dov-desktopstudie/0.1 (+https://github.com/Vorsie/dov-desktopstudie)"


class HttpError(Exception):
    def __init__(self, url: str, status: Optional[int], message: str):
        super().__init__(f"HTTP {status} for {url}: {message}")
        self.url = url
        self.status = status
        self.message = message


def build_url(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    if not params:
        return url
    query = urllib.parse.urlencode({k: str(v) for k, v in params.items()}, quote_via=urllib.parse.quote)
    return url + ("&" if "?" in url else "?") + query


def default_fetch(url: str, timeout: float, user_agent: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(url, exc.code, exc.reason) from exc
    except urllib.error.URLError as exc:
        raise HttpError(url, None, str(exc.reason)) from exc
    except TimeoutError as exc:
        raise HttpError(url, None, "timeout") from exc


class HttpClient:
    def __init__(self, cache_dir: Optional[Path] = None, timeout: float = 60.0, retries: int = 2,
                 backoff_s: float = 1.5, user_agent: str = USER_AGENT,
                 fetch: Optional[Callable[[str, float, str], bytes]] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = timeout
        self.retries = retries
        self.backoff_s = backoff_s
        self.user_agent = user_agent
        self._fetch = fetch or default_fetch
        self._sleep = sleep
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, full_url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(full_url.encode("utf-8")).hexdigest() + ".bin")

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        full = build_url(url, params)
        cached = self._cache_path(full)
        if cached and cached.exists():
            return cached.read_bytes()
        last: Optional[HttpError] = None
        for attempt in range(self.retries + 1):
            try:
                data = self._fetch(full, self.timeout, self.user_agent)
                if cached:
                    cached.write_bytes(data)
                    cached.with_suffix(".url").write_text(full, encoding="utf-8")
                return data
            except HttpError as exc:
                last = exc
                if exc.status is not None and exc.status < 500:
                    raise
                if attempt < self.retries:
                    self._sleep(self.backoff_s * (attempt + 1))
        assert last is not None
        raise last

    def get_text(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        return self.get(url, params).decode("utf-8")

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return json.loads(self.get_text(url, params))
