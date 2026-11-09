"""V2 Postgres sink — publishes classified legal items to the Mouhalis Legal
Intel V2 database so the lawyer-facing UI (clients, per-(event x client)
relevance, stage buttons, email drafts) sees pipeline output.

This is a direct-Postgres bridge because the V2 app is a Launchpad build and
its tokened ingestion endpoint is still awaiting admin approval for
machine-to-machine access. Writes go straight into V2's Postgres using the
same DATABASE_URL that V2 reads from.

Scope of what's published:
    - Pipeline keeps its full Item lifecycle in Notion (triage, interpretation,
      review workflow).
    - V2 receives the client-facing fields of items that have a content_class
      set and are not rejected/archived/superseded. The lawyer side then
      decides per-(event x client) relevance in V2 itself.

Idempotency:
    - Each Item upserts into V2 by `external_id = item.dedup_key()` (which is
      `<source_name>::<source_id>`). Re-running the pipeline on the same source
      produces the same external_id and updates the existing row — it does not
      duplicate it.

Offline / tests:
    - `psycopg` is imported lazily, so the Phase-0 fake-data walking skeleton
      and the unit tests keep running with no extra dependency.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from ..core.models import ContentClass, Item, ItemStatus

if TYPE_CHECKING:  # pragma: no cover - type hints only
    import psycopg

log = logging.getLogger(__name__)


# Statuses we DO NOT send to V2. Anything else with a content_class is sent.
_SKIP_STATUSES: frozenset[ItemStatus] = frozenset(
    {
        ItemStatus.NEW,
        ItemStatus.AWAITING_TRIAGE,
        ItemStatus.AWAITING_DEDUP_CONFIRMATION,
        ItemStatus.CLASS_A_AWAITING_INTERPRETATION,
        ItemStatus.REJECTED,
        ItemStatus.ARCHIVED,
        ItemStatus.SUPERSEDED,
    }
)


@dataclass(frozen=True)
class V2Payload:
    """The exact shape V2's `events` table consumes. Flat strings/arrays so
    the SQL parameters are obvious and the mapping is testable without any
    psycopg import."""

    external_id: str
    title: str
    source: str
    source_url: str
    published_on: Optional[str]  # YYYY-MM-DD or None
    event_type: str
    summary: str
    topics: list[str]


def _summary_for(item: Item) -> str:
    """Best client-facing summary we can produce from an Item: full
    interpretation summary when available, otherwise the normalized snippet,
    otherwise empty. The lawyer edits it in V2 either way."""
    if item.interpretation and item.interpretation.summary:
        return item.interpretation.summary.strip()
    if item.snippet:
        return item.snippet.strip()
    return ""


def item_to_payload(item: Item) -> Optional[V2Payload]:
    """Project an Item onto the V2 event shape, or return None if the Item is
    not ready for V2. Keeping this pure makes it trivial to unit-test without
    a database."""
    if item.content_class is None:
        return None
    if item.status in _SKIP_STATUSES:
        return None
    published = (
        item.date_published.isoformat() if item.date_published is not None else None
    )
    return V2Payload(
        external_id=f"{item.source_name}::{item.source_id}",
        title=item.title.strip(),
        source=item.source_name,
        source_url=item.url or "",
        published_on=published,
        event_type=item.type or "",
        summary=_summary_for(item),
        topics=list(item.topics or []),
    )


class V2Sink:
    """Thin wrapper around a `psycopg` connection to V2's Postgres.

    The connection string is passed in at construction (the pipeline reads it
    from the ``V2_DATABASE_URL`` environment variable). ``psycopg`` itself is
    imported inside ``__init__`` so importing this module in the walking
    skeleton — where psycopg isn't installed — doesn't fail.
    """

    def __init__(self, database_url: str) -> None:
        import psycopg  # noqa: F401 — the lazy import that gates runtime use

        self._database_url = database_url
        self._psycopg = psycopg

    # Factory used by the runner so a missing env var is a clean "disabled".
    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> Optional["V2Sink"]:
        import os

        url = (env or os.environ).get("V2_DATABASE_URL", "").strip()
        if not url:
            return None
        try:
            return cls(url)
        except ImportError:  # pragma: no cover - psycopg not installed in tests
            log.warning("psycopg not installed — V2 sink disabled")
            return None

    def publish(self, item: Item) -> bool:
        """Upsert an Item into V2's events table by `external_id`, and make
        sure every V2 client has a default-C ``event_clients`` row so the
        lawyer can refine it from the UI. Returns True on a write, False when
        the item was filtered out."""
        payload = item_to_payload(item)
        if payload is None:
            return False
        topics_json = json.dumps(payload.topics, ensure_ascii=False)
        try:
            with self._psycopg.connect(self._database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(_EXISTS_SQL, (payload.external_id,))
                    row = cur.fetchone()
                    if row is None:
                        cur.execute(
                            _INSERT_SQL,
                            {
                                "title": payload.title,
                                "source": payload.source,
                                "source_url": payload.source_url,
                                "published_on": payload.published_on,
                                "event_type": payload.event_type,
                                "summary": payload.summary,
                                "topics": topics_json,
                                "external_id": payload.external_id,
                            },
                        )
                        event_id = cur.fetchone()[0]
                        log.info(
                            "v2_sink: created event %s external_id=%s",
                            event_id,
                            payload.external_id,
                        )
                    else:
                        event_id = row[0]
                        cur.execute(
                            _UPDATE_SQL,
                            {
                                "external_id": payload.external_id,
                                "title": payload.title,
                                "source": payload.source,
                                "source_url": payload.source_url,
                                "published_on": payload.published_on,
                                "event_type": payload.event_type,
                                "summary": payload.summary,
                                "topics": topics_json,
                            },
                        )
                        log.info(
                            "v2_sink: updated event %s external_id=%s",
                            event_id,
                            payload.external_id,
                        )
                    cur.execute(_SEED_EVENT_CLIENTS_SQL, (event_id,))
                    conn.commit()
            return True
        except Exception as exc:  # pragma: no cover - any V2 error must NOT
            # kill the Notion write that already succeeded on this item.
            log.warning(
                "v2_sink: publish failed for external_id=%s: %s",
                payload.external_id,
                exc,
            )
            return False


_EXISTS_SQL = """
SELECT id FROM events WHERE external_id = %s LIMIT 1
"""

_INSERT_SQL = """
INSERT INTO events
    (id, title, source, source_url, published_on,
     event_type, summary, topics, external_id)
VALUES
    (gen_random_uuid()::text, %(title)s, %(source)s, %(source_url)s,
     %(published_on)s, %(event_type)s, %(summary)s,
     %(topics)s::jsonb, %(external_id)s)
RETURNING id
"""

_UPDATE_SQL = """
UPDATE events SET
    title = %(title)s,
    source = %(source)s,
    source_url = %(source_url)s,
    published_on = %(published_on)s,
    event_type = %(event_type)s,
    summary = %(summary)s,
    topics = %(topics)s::jsonb,
    updated_at = now()
WHERE external_id = %(external_id)s
"""

_SEED_EVENT_CLIENTS_SQL = """
INSERT INTO event_clients (event_id, client_id, relevance, decided_by)
SELECT %s, c.id, 'C', 'default' FROM clients c
ON CONFLICT (event_id, client_id) DO NOTHING
"""
