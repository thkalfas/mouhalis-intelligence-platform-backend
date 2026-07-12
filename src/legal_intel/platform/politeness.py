"""Shared scraping-politeness middleware (Story 3.1, AD-10).

ALL Tier-2 outbound requests route through this — a scraper must never issue a
raw request. Phase 0 ships the policy object and the enforcing wrapper; the
concrete HTTP call is provided by Tier-2 adapters in Epic 3.

Policy (spec §12): ≤1 req / 5s per domain, ±30% jitter, non-identifying rotating
UA, robots.txt respected, max 1 concurrent/domain, circuit breaker (3× 429/503
in 5 min → 30-min pause), backoff 2/4/8/16/32s.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BACKOFF_SCHEDULE = (2, 4, 8, 16, 32)

# A pool of realistic, non-identifying UA strings (AD-10: never brand as REBORRN).
USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
)


@dataclass
class PolitenessPolicy:
    min_interval_s: float = 5.0
    jitter_frac: float = 0.30
    max_concurrent_per_domain: int = 1
    breaker_threshold: int = 3
    breaker_window_s: float = 300.0
    breaker_pause_s: float = 1800.0
    respect_robots: bool = True


@dataclass
class DomainState:
    last_request_ts: float = 0.0
    recent_errors: list[float] = field(default_factory=list)
    paused_until: float = 0.0


class CircuitOpen(RuntimeError):
    """Raised when a domain's breaker is open (paused)."""


class PolitenessMiddleware:
    """Tracks per-domain timing and breaker state. The `now`/`sleep` seam keeps
    it testable without real time."""

    def __init__(self, policy: PolitenessPolicy | None = None) -> None:
        self.policy = policy or PolitenessPolicy()
        self._domains: dict[str, DomainState] = {}

    def _state(self, domain: str) -> DomainState:
        return self._domains.setdefault(domain, DomainState())

    def note_error(self, domain: str, now: float) -> bool:
        """Record a 429/503; return True if the breaker just opened."""
        st = self._state(domain)
        st.recent_errors = [t for t in st.recent_errors
                            if now - t <= self.policy.breaker_window_s]
        st.recent_errors.append(now)
        if len(st.recent_errors) >= self.policy.breaker_threshold:
            st.paused_until = now + self.policy.breaker_pause_s
            st.recent_errors.clear()
            return True
        return False

    def is_paused(self, domain: str, now: float) -> bool:
        return now < self._state(domain).paused_until

    def next_allowed_ts(self, domain: str) -> float:
        return self._state(domain).last_request_ts + self.policy.min_interval_s

    def mark_request(self, domain: str, now: float) -> None:
        self._state(domain).last_request_ts = now
