"""Small, patient HTTP client for the UK Parliament APIs.

The Written Questions API can take 10-40 seconds per request and returns
HTTP 500 when its own ~30 second limit is hit, so every call here uses long
timeouts and retries with back-off. Never send includeTotalResults=true: it
makes date-range queries time out.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

QS_API = "https://questions-statements-api.parliament.uk/api"
MEMBERS_API = "https://members-api.parliament.uk/api"
USER_AGENT = "parliamentary-briefing/1.0 (daily public-affairs digest; GitHub Actions)"

log = logging.getLogger("api")


class Api:
    def __init__(self, timeout: float = 180.0, backoff: tuple[float, ...] = (15, 30, 60, 120),
                 transport: httpx.BaseTransport | None = None):
        self.backoff = backoff
        self.client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT},
                                   transport=transport, follow_redirects=True)
        self.calls = 0
        self.failures: list[str] = []

    def close(self) -> None:
        self.client.close()

    def get(self, url: str, params: dict[str, Any] | None = None, *, retries: int | None = None) -> Any:
        waits = self.backoff if retries is None else self.backoff[:retries]
        last = ""
        for attempt in range(len(waits) + 1):
            t0 = time.monotonic()
            try:
                self.calls += 1
                r = self.client.get(url, params=params)
                if r.status_code == 200:
                    log.debug("GET %s %s %.1fs", url, params, time.monotonic() - t0)
                    return r.json()
                last = f"HTTP {r.status_code}"
                if r.status_code == 404:
                    break
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = type(e).__name__
            log.warning("GET %s failed (%s) after %.1fs, attempt %d", url, last, time.monotonic() - t0, attempt + 1)
            if attempt < len(waits):
                time.sleep(waits[attempt])
        self.failures.append(f"{url} {params or ''}: {last}")
        return None

    def get_all(self, path: str, params: dict[str, Any], page: int = 1000, max_pages: int = 20) -> tuple[list[dict], bool]:
        """Page through a Questions & Statements list endpoint. Returns (values, complete)."""
        out: list[dict] = []
        for n in range(max_pages):
            data = self.get(f"{QS_API}/{path}", {**params, "take": page, "skip": n * page})
            if data is None:
                return out, False
            results = data.get("results", [])
            out.extend(r.get("value", r) for r in results)
            if len(results) < page:
                return out, True
        return out, False
