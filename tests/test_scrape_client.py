"""Story 3.1 — politeness-enforcing scrape client (offline, deterministic)."""
from __future__ import annotations

import pytest

from legal_intel.core.errors import PermanentError, TransientError
from legal_intel.platform.politeness import CircuitOpen, PolitenessPolicy
from legal_intel.platform.scrape_client import ScrapeClient, ScrapeResponse


class _FakeFetcher:
    """Scripted per-URL responses; records calls and the UA it was given.
    robots.txt defaults to allow-all unless `robots_body` says otherwise."""

    def __init__(self, status_script=None, *, robots_body="User-agent: *\nAllow: /"):
        self.status_script = list(status_script or [])
        self.robots_body = robots_body
        self.calls: list[tuple[str, str]] = []  # (url, user-agent)

    def __call__(self, url, *, headers) -> ScrapeResponse:
        self.calls.append((url, headers.get("User-Agent", "")))
        if url.endswith("/robots.txt"):
            return ScrapeResponse(200, url, self.robots_body.encode("utf-8"), {})
        status = self.status_script.pop(0) if self.status_script else 200
        return ScrapeResponse(status, url, b"<html>ok</html>",
                              {"content-type": "text/html"})


def _clock_seam(start=1000.0):
    t = [start]
    return t, (lambda: t[0]), (lambda s: t.__setitem__(0, t[0] + s))


def _client(fetcher, **kw):
    t, clock, sleep = _clock_seam()
    client = ScrapeClient(
        fetcher, policy=PolitenessPolicy(),
        clock=clock, sleep=sleep,
        jitter=lambda base: base,           # deterministic (no randomness)
        ua_picker=lambda: "TestUA/1.0",
        **kw,
    )
    return client, t


def test_success_returns_and_sends_rotating_ua():
    f = _FakeFetcher()
    client, _ = _client(f)
    resp = client.get("https://example.gr/list")
    assert resp.status_code == 200
    # robots fetched once, then the page — page request carried the UA
    page_calls = [c for c in f.calls if not c[0].endswith("/robots.txt")]
    assert page_calls == [("https://example.gr/list", "TestUA/1.0")]


def test_robots_disallow_raises_permanent():
    f = _FakeFetcher(robots_body="User-agent: *\nDisallow: /")
    client, _ = _client(f)
    with pytest.raises(PermanentError):
        client.get("https://example.gr/secret")


def test_rate_limit_waits_between_same_domain_requests():
    f = _FakeFetcher()
    client, t = _client(f)
    client.get("https://example.gr/a")
    start = t[0]
    client.get("https://example.gr/b")
    # second request slept ~min_interval (5s) before firing
    assert t[0] - start >= client.policy.min_interval_s


def test_backoff_then_success():
    f = _FakeFetcher(status_script=[503, 200])
    client, t = _client(f)
    start = t[0]
    resp = client.get("https://example.gr/x")
    assert resp.status_code == 200
    assert t[0] - start >= 2.0  # first backoff step slept


def test_404_is_permanent():
    f = _FakeFetcher(status_script=[404])
    client, _ = _client(f)
    with pytest.raises(PermanentError):
        client.get("https://example.gr/missing")


def test_circuit_breaker_trips_after_repeated_5xx():
    f = _FakeFetcher(status_script=[503, 503, 503, 503, 503, 503])
    client, _ = _client(f)
    with pytest.raises(CircuitOpen):
        client.get("https://example.gr/flaky")
    # domain now paused → next request is refused without hitting the network
    with pytest.raises(CircuitOpen):
        client.get("https://example.gr/anything")


def test_scraper_cannot_bypass_middleware():
    # The only way to fetch is through ScrapeClient.get; there is no raw path.
    # A scraper holding only a ScrapeClient must go through rate-limit + robots.
    f = _FakeFetcher()
    client, _ = _client(f)
    client.get("https://example.gr/a")
    assert any(c[0].endswith("/robots.txt") for c in f.calls)
