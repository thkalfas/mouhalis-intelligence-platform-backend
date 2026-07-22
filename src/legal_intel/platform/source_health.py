"""Source-health board writer (FR-20 ops surface).

After each source run the scheduler/CLI records that source's outcome — last
status, items collected, errors, and a note — into the Notion "Source Health"
database, so operators have an at-a-glance coverage board (which sources ran,
which failed and why). Writes are Notion-only (no LLM), keyed by source name,
and never touch the human-curated Description column.

Enabled only when the real Notion backend is on AND NOTION_SOURCE_HEALTH_DB_ID is
set; otherwise the writer is a no-op, so the offline skeleton is unaffected.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol


@dataclass
class SourceHealth:
    source: str
    tier: int
    adapter: str
    enabled: bool
    status: str  # Success | Degraded | Failure | Not run
    items_collected: int = 0
    filtered: int = 0
    errors: int = 0
    cadence: str = ""
    authority_rank: Optional[int] = None
    notes: Optional[str] = None
    last_run: Optional[datetime] = None


def status_from_report(persisted: int, errors: int) -> str:
    """Success = clean; Degraded = wrote some but hit item errors; Failure =
    ran but wrote nothing."""
    if errors and persisted:
        return "Degraded"
    if errors and not persisted:
        return "Failure"
    return "Success"


class SourceHealthBackend(Protocol):
    def upsert(self, rec: SourceHealth) -> None: ...


class LocalSourceHealthBackend:
    """In-memory board for tests/offline (keyed by source name)."""

    def __init__(self) -> None:
        self.rows: dict[str, SourceHealth] = {}

    def upsert(self, rec: SourceHealth) -> None:
        self.rows[rec.source] = rec


class NotionSourceHealthBackend:  # pragma: no cover - needs network + token
    def __init__(self, token: Optional[str] = None, database_id: Optional[str] = None):
        from notion_client import Client

        self._client = Client(auth=token or os.environ["NOTION_TOKEN"])
        self._database_id = database_id or os.environ["NOTION_SOURCE_HEALTH_DB_ID"]
        self._ds: Optional[str] = None

    def _ds_id(self) -> str:
        if not self._ds:
            db = self._client.databases.retrieve(database_id=self._database_id)
            self._ds = (db.get("data_sources") or [{}])[0]["id"]
        return self._ds

    def _find(self, source: str) -> Optional[str]:
        resp = self._client.data_sources.query(
            data_source_id=self._ds_id(),
            filter={"property": "Source", "title": {"equals": source}},
            page_size=1,
        )
        results = resp.get("results", [])
        return results[0]["id"] if results else None

    def upsert(self, rec: SourceHealth) -> None:
        def rt(v):
            return {"rich_text": [{"type": "text", "text": {"content": (v or "")[:2000]}}]}

        # Operational fields only — Description is human-curated and left alone.
        props: dict = {
            "Tier": {"select": {"name": str(rec.tier)}},
            "Adapter": rt(rec.adapter),
            "Enabled": {"checkbox": bool(rec.enabled)},
            "Last Status": {"select": {"name": rec.status}},
            "Items Collected": {"number": rec.items_collected},
            "Filtered (old)": {"number": rec.filtered},
            "Errors": {"number": rec.errors},
            "Cadence": rt(rec.cadence),
            "Last Error / Notes": rt(rec.notes or ""),
        }
        if rec.authority_rank is not None:
            props["Authority Rank"] = {"number": rec.authority_rank}
        when = (rec.last_run or datetime.now(timezone.utc)).isoformat()
        props["Last Run"] = {"date": {"start": when}}

        page_id = self._find(rec.source)
        if page_id:
            self._client.pages.update(page_id=page_id, properties=props)
        else:
            props["Source"] = {"title": [{"type": "text", "text": {"content": rec.source}}]}
            self._client.pages.create(
                parent={"type": "data_source_id", "data_source_id": self._ds_id()},
                properties=props,
            )


def make_source_health_backend() -> Optional[SourceHealthBackend]:
    """Notion board when configured, else None (writer becomes a no-op)."""
    if (os.environ.get("LEGAL_INTEL_NOTION_BACKEND", "local").lower() == "notion"
            and os.environ.get("NOTION_SOURCE_HEALTH_DB_ID")):
        return NotionSourceHealthBackend()  # pragma: no cover
    return None


class SourceHealthWriter:
    def __init__(self, backend: Optional[SourceHealthBackend] = None) -> None:
        self._backend = backend if backend is not None else make_source_health_backend()

    @property
    def active(self) -> bool:
        return self._backend is not None

    def record(self, rec: SourceHealth) -> None:
        if self._backend is not None:
            self._backend.upsert(rec)
