"""Minimal HTTP client on urllib: GET with timeout, retry on 5xx/network errors, optional disk
cache keyed by the full URL. The fetch function is injectable for tests."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import client as http_client
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..logging_util import Log

USER_AGENT = "dov-desktopstudie/0.1 (+https://github.com/Vorsie/dov-desktopstudie)"

CACHE_MODES = ("use", "refresh", "off")
RETRYABLE_STATUSES = (408, 429)


def short_url(url: str) -> str:
    """The URL without its query string, plus the WFS request and typeNames when it carries them.
    A DOV GetFeature URL holds the whole CQL polygon: repeating that in every log line and in every
    provenance message buries the failure itself, while the bare path alone would no longer say
    WHICH layer failed. `HttpError.url` keeps the full URL for whoever has to retry it."""
    base, _, query = url.partition("?")
    values = urllib.parse.parse_qs(query)
    lowered = {key.lower(): vals[0] for key, vals in values.items() if vals}
    named = [lowered[key] for key in ("request", "typenames") if lowered.get(key)]
    return f"{base} ({' '.join(named)})" if named else base


class HttpError(Exception):
    def __init__(self, url: str, status: Optional[int], message: str):
        self.url = url
        self.status = status
        self.message = message
        super().__init__(url, status, message)

    def __str__(self) -> str:
        where = short_url(self.url)
        if self.status is not None:
            return f"HTTP {self.status} voor {where}: {self.message}"
        return f"netwerkfout voor {where}: {self.message}"


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
    except (OSError, http_client.HTTPException) as exc:
        # covers socket.timeout (Python 3.9), ConnectionResetError and http.client.IncompleteRead /
        # RemoteDisconnected -- failures that urllib does not itself wrap in HTTPError/URLError.
        raise HttpError(url, None, f"{type(exc).__name__}: {exc}") from exc


class HttpClient:
    def __init__(self, cache_dir: Optional[Path] = None, timeout: float = 60.0, retries: int = 2,
                 backoff_s: float = 1.5, user_agent: str = USER_AGENT,
                 fetch: Optional[Callable[[str, float, str], bytes]] = None,
                 sleep: Callable[[float], None] = time.sleep, log: Optional[Log] = None,
                 cache_mode: str = "use"):
        if cache_mode not in CACHE_MODES:
            raise ValueError(f"unknown cache_mode {cache_mode!r}; use one of {CACHE_MODES}")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff_s = backoff_s
        self.user_agent = user_agent
        self._fetch = fetch or default_fetch
        self._sleep = sleep
        self.log = log
        self.cache_mode = cache_mode
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, full_url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(full_url.encode("utf-8")).hexdigest() + ".bin")

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        """Write via a pid+thread-scoped temp file and os.replace so concurrent writers never see
        a half-written cache entry; a failed cache write must never fail the request itself."""
        tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            pass

    def _retryable(self, exc: HttpError) -> bool:
        return exc.status is None or exc.status >= 500 or exc.status in RETRYABLE_STATUSES

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        full = build_url(url, params)
        cached = self._cache_path(full)
        if cached and self.cache_mode == "use" and cached.exists():
            return cached.read_bytes()
        last: Optional[HttpError] = None
        attempt = 0
        for attempt in range(self.retries + 1):
            try:
                data = self._fetch(full, self.timeout, self.user_agent)
                if cached and self.cache_mode != "off":
                    self._atomic_write(cached, data)
                    self._atomic_write(cached.with_suffix(".url"), full.encode("utf-8"))
                return data
            except HttpError as exc:
                last = exc
                if not self._retryable(exc):
                    raise
                if attempt < self.retries:
                    if self.log:
                        self.log.debug(f"retry {attempt + 1}/{self.retries} na {exc.status or 'netwerkfout'} "
                                        f"voor {full}")
                    self._sleep(self.backoff_s * (attempt + 1))
        if last is not None:
            if self.log:
                self.log.warning(f"definitief mislukt na {attempt + 1} pogingen voor {full}: {last}")
            raise last
        raise HttpError(url, None, "no attempts")

    def get_text(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        return self.get(url, params).decode("utf-8")

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        raw = self.get_text(url, params)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            full_url = build_url(url, params)
            raise HttpError(full_url, 200, f"geen JSON in het antwoord: {raw[:200]!r}") from exc
