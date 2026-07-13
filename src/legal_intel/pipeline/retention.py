"""Class-aware retention (Story 6.3, FR-9, AD-5/AD-2).

Retention follows Content Class (spec §7.5/§7.6):
  - Class B — index-only: metadata + URL, no full text (enforced at triage and
    again in the NotionGateway payload). Nothing here to expire.
  - Class C — transient: full text is authoritative in Notion while a human
    decides, but only for a TTL (default 7 days). Past the TTL without a
    decision the Item is flagged ``overdue`` (an SLA-breach signal); it stays in
    the queue until resolved.
  - Resolution (WF1, human): promote to A (verifying full text is actually
    present before flipping class — AD-2) or downgrade to B (purging full text).

These are the retention mechanics; Epic 8 wires the Notion review queue on top.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core import state_machine as sm
from ..core.config import AppConfig
from ..core.errors import PermanentError
from ..core.models import ContentClass, Item, ItemStatus
from ..core.notion_gateway import NotionGateway


def _now() -> datetime:
    return datetime.now(timezone.utc)


def class_c_expired(item: Item, cfg: AppConfig, now: Optional[datetime] = None) -> bool:
    """True if a Class C Item has sat past its staging TTL without a decision."""
    if item.content_class is not ContentClass.C:
        return False
    if item.status is not ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW:
        return False
    now = now or _now()
    ttl = timedelta(days=cfg.triage.class_c_ttl_days)
    return (now - item.collected_at) > ttl


def sweep_overdue(items: list[Item], cfg: AppConfig,
                  now: Optional[datetime] = None,
                  gateway: Optional[NotionGateway] = None) -> list[Item]:
    """Flag Class C Items past TTL as ``overdue`` (spec §7.6). Returns the newly
    flagged Items; persists them if a gateway is supplied."""
    now = now or _now()
    flagged: list[Item] = []
    for item in items:
        if class_c_expired(item, cfg, now) and not item.overdue:
            item.overdue = True
            flagged.append(item)
            if gateway is not None:
                gateway.upsert_item(item)
    return flagged


def promote_class_c_to_a(item: Item, gateway: NotionGateway) -> Item:
    """WF1 'Classify as A' (HUMAN): flip a Class C Item to A and enqueue
    interpretation. AD-2 — refuse unless full text is actually present, so we
    never promote an empty record (the caller re-fetches first if needed)."""
    if not item.full_text:
        raise PermanentError(
            f"Cannot promote {item.dedup_key()} to Class A: full text absent "
            f"(re-fetch from source first, AD-2)"
        )
    sm.assert_transition(item.status,
                         ItemStatus.CLASS_A_AWAITING_INTERPRETATION, sm.Actor.HUMAN)
    item.content_class = ContentClass.A
    item.status = ItemStatus.CLASS_A_AWAITING_INTERPRETATION
    item.overdue = False
    gateway.upsert_item(item)
    return item


def downgrade_class_c_to_b(item: Item, gateway: NotionGateway) -> Item:
    """WF1 'Classify as B' (HUMAN): downgrade to index-only, purging full text
    and snippet (AD-5)."""
    sm.assert_transition(item.status, ItemStatus.CLASS_B_INDEXED, sm.Actor.HUMAN)
    item.content_class = ContentClass.B
    item.status = ItemStatus.CLASS_B_INDEXED
    item.full_text = None
    item.snippet = None
    item.overdue = False
    gateway.upsert_item(item)
    return item
