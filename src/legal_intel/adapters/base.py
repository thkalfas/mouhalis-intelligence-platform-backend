"""The one Source Adapter contract (Story 0.7, AD-3).

New sources add an adapter; they never modify downstream stages. A failing
adapter isolates to its own job (AD-12) — the ingestion driver wraps fetch().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from ..core.models import SourceRecord


class SourceAdapter(ABC):
    #: Human-readable source name; must match a `sources.yaml` entry.
    name: str = ""
    #: 1, 2, or 3.
    tier: int = 0

    @abstractmethod
    def fetch(self) -> Iterable[SourceRecord]:
        """Yield SourceRecords for Legal Events observed since the last run.

        Implementations MUST populate the mandatory field set on each record and
        MUST be safe to call repeatedly (idempotency is enforced downstream by
        the dedup key, AD-4, but adapters should not double-emit within one run).
        """
        raise NotImplementedError
