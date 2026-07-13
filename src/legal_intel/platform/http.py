"""Shared Tier-1 HTTP client (Epic 1 support for FR-1).

Tier-1 adapters talk to official REST/SPARQL/RSS endpoints — no politeness
middleware (that is Tier-2 scraping, AD-10), but the same reliability contract:
exponential backoff on 429/503/5xx (spec §5.1.1) as ``TransientError``, and
``PermanentError`` on 404/410 so a bad item is alerted+skipped, not retried
forever (AD-12).

``httpx`` is lazy-imported by the default transport only. Adapters accept an
injected client, so their tests run fully offline against fixture responses and
never import httpx — the same offline-first seam as the fake LLM/Notion backends.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from ..core.errors import PermanentError, TransientError

DEFAULT_BACKOFF = (2.0, 4.0, 8.0, 16.0, 32.0)  # spec §5.1.1
DEFAULT_TIMEOUT_S = 60.0  # EUR-Lex SPARQL query timeout is 60s
_RETRY_STATUS = {429, 500, 502, 503, 504}
_PERMANENT_STATUS = {400, 401, 403, 404, 410}


@dataclass
class HttpResponse:
    status_code: int
    url: str
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return self.content.decode("utf-8", errors="replace")

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


class Transport(Protocol):
    """The single network seam. A real transport hits the wire; a test transport
    returns fixtures."""

    def __call__(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> HttpResponse: ...


def _httpx_transport(timeout: float) -> Transport:
    def _send(method, url, *, params=None, headers=None) -> HttpResponse:
        import httpx  # lazy — only the real transport needs it

        resp = httpx.request(
            method, url, params=params, headers=headers,
            timeout=timeout, follow_redirects=True,
        )
        return HttpResponse(
            status_code=resp.status_code,
            url=str(resp.url),
            content=resp.content,
            headers={k.lower(): v for k, v in resp.headers.items()},
        )

    return _send


class HttpClient:
    """Reliability wrapper over a Transport. ``sleep`` is a seam so backoff is
    instant in tests."""

    def __init__(
        self,
        transport: Optional[Transport] = None,
        *,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        timeout: float = DEFAULT_TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
        default_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self._transport = transport or _httpx_transport(timeout)
        self._backoff = backoff
        self._sleep = sleep
        self._default_headers = default_headers or {
            "Accept-Language": "el,en;q=0.9",
        }

    def get(
        self,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        accept: Optional[str] = None,
    ) -> HttpResponse:
        merged = dict(self._default_headers)
        if accept:
            merged["Accept"] = accept
        if headers:
            merged.update(headers)
        return self._request("GET", url, params=params, headers=merged)

    def _request(self, method, url, *, params, headers) -> HttpResponse:
        last_exc: Optional[Exception] = None
        # len(backoff) retries after the initial attempt.
        for attempt in range(len(self._backoff) + 1):
            resp = self._transport(method, url, params=params, headers=headers)
            if resp.status_code in _PERMANENT_STATUS:
                raise PermanentError(f"HTTP {resp.status_code} for {url}")
            if resp.status_code in _RETRY_STATUS:
                last_exc = TransientError(f"HTTP {resp.status_code} for {url}")
                if attempt < len(self._backoff):
                    self._sleep(self._backoff[attempt])
                    continue
                raise last_exc
            if resp.status_code >= 400:
                raise PermanentError(f"HTTP {resp.status_code} for {url}")
            return resp
        raise last_exc or TransientError(f"exhausted retries for {url}")
