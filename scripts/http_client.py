"""HTTP-клиент с rate-limiting и retry.

Используется source-адаптерами:
    client = HttpClient(rate_limit_rps=1.0)
    data = client.get_json("https://api.example.com/v1/jobs")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    """Минимальный token-bucket — однопоточный, без блокировок."""

    rps: float
    last_call_at: float = 0.0

    def wait(self) -> None:
        if self.rps <= 0:
            return
        gap = 1.0 / self.rps
        now = time.monotonic()
        elapsed = now - self.last_call_at
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self.last_call_at = time.monotonic()


class HttpClient:
    def __init__(
        self,
        *,
        rate_limit_rps: float = 1.0,
        timeout: float = 30.0,
        user_agent: str = "kvetio-agent/2.0 (+https://kvet.io)",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._bucket = _Bucket(rps=rate_limit_rps)
        headers: dict[str, str] = {
            "User-Agent": user_agent,
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.Client(
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    def get_json(self, url: str, *, params: dict | None = None) -> dict | list:
        self._bucket.wait()
        logger.debug("GET %s params=%s", url, params)
        resp = self._client.get(url, params=params)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    def get_text(self, url: str, *, params: dict | None = None) -> str:
        """GET a non-JSON payload (e.g. Atom/XML, RSS) as raw text.

        Returns an empty string on 404 so resolvers can treat "no data" uniformly.
        """
        self._bucket.wait()
        logger.debug("GET(text) %s params=%s", url, params)
        resp = self._client.get(url, params=params, headers={"Accept": "*/*"})
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.text
