"""Politeness-enforcing scrape client (Story 3.1, FR-2, AD-10).

The single choke point for ALL Tier-2 outbound requests — a scraper must never
issue a raw request. It layers the Phase-0 ``PolitenessMiddleware`` (per-domain
timing + circuit-breaker state) into an actual fetch flow that enforces:

  - ≤1 request / 5s per domain, with ±30% jitter,
  - a non-identifying rotating User-Agent (never REBORRN branding, AD-10),
  - robots.txt respect (fail-open if robots is unreachable),
  - max 1 concurrent request per domain (a per-domain lock),
  - exponential backoff 2/4/8/16/32s on 429/503,
  - circuit breaker: 3× 429/503 within 5 min pauses the domain 30 min.

The network call, the clock, sleep, jitter and UA choice are all injectable
seams, so the whole policy is unit-tested offline with zero real waiting and no
network — the same offline-first discipline as the Tier-1 HttpClient.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from ..core.errors import PermanentError, TransientError
from .logging import get_logger
from .politeness import (BACKOFF_SCHEDULE, USER_AGENTS, CircuitOpen,
                         PolitenessMiddleware, PolitenessPolicy)

_RETRY_STATUS = {429, 500, 502, 503, 504}
_PERMANENT_STATUS = {400, 401, 403, 404, 410}


@dataclass
class ScrapeResponse:
    status_code: int
    url: str
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("latin-1", errors="replace")


class Fetcher(Protocol):
    """The raw network seam a scrape backend provides (httpx for static HTML,
    Playwright for JS-heavy sites). Receives the chosen UA in ``headers``."""

    def __call__(self, url: str, *, headers: dict[str, str]) -> ScrapeResponse: ...


def _httpx_fetcher(timeout: float = 30.0) -> Fetcher:
    """Default static-HTML fetcher (lazy httpx). JS-heavy sites inject a
    Playwright-backed fetcher instead."""
    def _send(url, *, headers) -> ScrapeResponse:
        import httpx  # lazy — only the real fetcher needs it

        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        return ScrapeResponse(
            status_code=resp.status_code, url=str(resp.url), content=resp.content,
            headers={k.lower(): v for k, v in resp.headers.items()},
        )

    return _send


class ScrapeClient:
    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        middleware: Optional[PolitenessMiddleware] = None,
        *,
        policy: Optional[PolitenessPolicy] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Optional[Callable[[float], float]] = None,
        ua_picker: Optional[Callable[[], str]] = None,
    ) -> None:
        self._fetch = fetcher or _httpx_fetcher()
        self.policy = policy or PolitenessPolicy()
        self.mw = middleware or PolitenessMiddleware(self.policy)
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter or self._default_jitter
        self._ua_picker = ua_picker or (lambda: random.choice(USER_AGENTS))
        self._domain_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self.log = get_logger()

    # -- seams ------------------------------------------------------------- #
    def _default_jitter(self, base: float) -> float:
        frac = self.policy.jitter_frac
        return base * (1.0 + random.uniform(-frac, frac))

    def _domain_lock(self, domain: str) -> threading.Lock:
        with self._locks_guard:
            return self._domain_locks.setdefault(domain, threading.Lock())

    # -- robots ------------------------------------------------------------ #
    def _robots_for(self, scheme: str, domain: str) -> Optional[RobotFileParser]:
        if domain in self._robots:
            return self._robots[domain]
        rp: Optional[RobotFileParser] = None
        try:
            resp = self._fetch(f"{scheme}://{domain}/robots.txt",
                               headers={"User-Agent": self._ua_picker()})
            if resp.status_code < 400 and resp.text.strip():
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
        except Exception:  # robots unreachable → fail open (allow)
            rp = None
        self._robots[domain] = rp
        return rp

    def _robots_allows(self, url: str, ua: str) -> bool:
        parts = urlparse(url)
        rp = self._robots_for(parts.scheme or "https", parts.netloc)
        return True if rp is None else rp.can_fetch(ua, url)

    # -- fetch ------------------------------------------------------------- #
    def get(self, url: str, *, headers: Optional[dict[str, str]] = None) -> ScrapeResponse:
        domain = urlparse(url).netloc
        with self._domain_lock(domain):  # max 1 concurrent per domain (AD-10)
            return self._get_locked(url, domain, headers)

    def _get_locked(self, url, domain, headers) -> ScrapeResponse:
        now = self._clock()
        if self.mw.is_paused(domain, now):
            raise CircuitOpen(f"circuit open for {domain}")

        ua = self._ua_picker()
        if self.policy.respect_robots and not self._robots_allows(url, ua):
            raise PermanentError(f"robots.txt disallows {url}")

        # Rate limit: wait until the domain's next allowed slot, plus jitter.
        wait = self.mw.next_allowed_ts(domain) - now
        if wait > 0:
            self._sleep(self._jitter(wait))

        last_exc: Optional[Exception] = None
        for attempt in range(len(BACKOFF_SCHEDULE) + 1):
            merged = {"User-Agent": ua, "Accept-Language": "el,en;q=0.9"}
            if headers:
                merged.update(headers)
            resp = self._fetch(url, headers=merged)
            self.mw.mark_request(domain, self._clock())

            if resp.status_code in _RETRY_STATUS:
                opened = self.mw.note_error(domain, self._clock())
                self.log.log(source="scrape", event="retryable_status",
                             status=str(resp.status_code), item_id=domain)
                if opened:
                    raise CircuitOpen(f"circuit opened for {domain}")
                last_exc = TransientError(f"HTTP {resp.status_code} for {url}")
                if attempt < len(BACKOFF_SCHEDULE):
                    self._sleep(BACKOFF_SCHEDULE[attempt])
                    continue
                raise last_exc
            if resp.status_code in _PERMANENT_STATUS or resp.status_code >= 400:
                raise PermanentError(f"HTTP {resp.status_code} for {url}")
            return resp
        raise last_exc or TransientError(f"exhausted retries for {url}")
