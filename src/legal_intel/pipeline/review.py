"""Human-in-the-loop review workflows (Epic 8, FR-13/14/15/18/22).

The queue mechanics — assignment, SLA, escalation, the A/B and approve/reject
decisions, and the B→A reclassify re-fetch — are deterministic logic here in
Environment A; the reviewers act through Notion, and every transition goes
through the state machine as the HUMAN actor (AD-6). The Quality Observer
(agents/quality_observer.py) reads the timestamps these functions stamp.

WF1 Class C relevance review · WF2 interpretation review + feedback · WF3
client-impact/action planning · bidirectional edits · B→A reclassify.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from ..core import state_machine as sm
from ..core.config import AppConfig
from ..core.errors import PermanentError
from ..core.llm_client import MeteredLLMClient
from ..core.models import ContentClass, Interpretation, Item, ItemStatus
from ..core.notion_gateway import NotionGateway
from ..platform.alerting import AlertLevel, get_alerter
from ..platform.logging import get_logger
from . import interpret as interpret_mod
from . import retention as retention_mod

_log = get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Reviewer assignment (expertise-first, then least-loaded) — WF1/WF2 routing
# --------------------------------------------------------------------------- #
def assign_reviewer(item: Item, reviewers: list[dict]) -> Optional[str]:
    """Pick a reviewer: prefer one whose expertise covers a Topic of the Item,
    breaking ties by lowest current queue depth; fall back to the least-loaded
    available reviewer. ``reviewers`` = [{name, expertise[], available, queue_depth,
    max_concurrent}]."""
    available = [r for r in reviewers if r.get("available", True)
                 and r.get("queue_depth", 0) < r.get("max_concurrent", 10**9)]
    if not available:
        return None
    topics = set(item.topics)
    experts = [r for r in available if topics & set(r.get("expertise", []))]
    pool = experts or available
    return min(pool, key=lambda r: r.get("queue_depth", 0))["name"]


# --------------------------------------------------------------------------- #
# WF1 — Class C relevance review (Story 8.1)
# --------------------------------------------------------------------------- #
def enqueue_relevance_review(item: Item, reviewer: Optional[str],
                             gateway: NotionGateway,
                             now: Optional[datetime] = None) -> Item:
    """Assign a Class C Item to the relevance-review queue and stamp the SLA clock."""
    item.reviewer = reviewer
    item.class_c_assigned_at = now or _now()
    gateway.upsert_item(item)
    return item


def relevance_review(item: Item, decision: str, reviewer: str,
                     gateway: NotionGateway, *, reason: Optional[str] = None,
                     now: Optional[datetime] = None) -> Item:
    """WF1 decision (HUMAN): 'A' promotes to interpretation (retention verifies
    full text is present, AD-2), 'B' downgrades to index-only. Records the
    decision, reason, reviewer, and timestamp."""
    now = now or _now()
    item.reviewer = reviewer
    item.review_notes = reason
    item.class_c_decided_at = now
    if decision == "A":
        retention_mod.promote_class_c_to_a(item, gateway)
    elif decision == "B":
        retention_mod.downgrade_class_c_to_b(item, gateway)
    else:
        raise PermanentError(f"WF1 decision must be 'A' or 'B', got {decision!r}")
    gateway.upsert_item(item)
    return item


# --------------------------------------------------------------------------- #
# WF2 — interpretation review + feedback (Story 8.2)
# --------------------------------------------------------------------------- #
def wf2_sla(item: Item) -> dict:
    """Review SLA: 24h fast-track for `action_signal == immediate`, else 3
    business days (spec §9.2)."""
    if item.action_signal == "immediate":
        return {"hours": 24}
    return {"business_days": 3}


def _diff_interpretation(old: Optional[Interpretation],
                         new: Interpretation) -> dict:
    """Field-level diff captured as reviewer feedback (drives prompt tuning)."""
    if old is None:
        return {"_new": True}
    old_d, new_d = old.model_dump(), new.model_dump()
    return {k: {"from": old_d.get(k), "to": new_d.get(k)}
            for k in new_d if old_d.get(k) != new_d.get(k)}


def approve_interpretation(item: Item, reviewer: str, gateway: NotionGateway,
                           now: Optional[datetime] = None) -> Item:
    sm.assert_transition(item.status, ItemStatus.APPROVED, sm.Actor.HUMAN)
    item.status = ItemStatus.APPROVED
    item.reviewer = reviewer
    item.review_completed_at = now or _now()
    gateway.upsert_item(item)
    return item


def edit_and_approve(item: Item, edited: Interpretation, reviewer: str,
                     gateway: NotionGateway, now: Optional[datetime] = None) -> Item:
    """Reviewer edits fields inline then approves; the diff is captured as
    feedback for later prompt tuning (spec §9.2)."""
    sm.assert_transition(item.status, ItemStatus.APPROVED, sm.Actor.HUMAN)
    item.review_feedback = _diff_interpretation(item.interpretation, edited)
    item.interpretation = edited
    item.status = ItemStatus.APPROVED
    item.reviewer = reviewer
    item.review_completed_at = now or _now()
    gateway.upsert_item(item)
    return item


def reject_and_redo(item: Item, notes: str, reviewer: str,
                    gateway: NotionGateway, now: Optional[datetime] = None) -> Item:
    """Reject the draft with notes; the Item awaits regeneration with the notes
    as added context."""
    sm.assert_transition(item.status, ItemStatus.REJECTED, sm.Actor.HUMAN)
    item.status = ItemStatus.REJECTED
    item.reviewer = reviewer
    item.review_notes = notes
    item.review_completed_at = now or _now()
    gateway.upsert_item(item)
    return item


def regenerate_after_reject(item: Item, cfg: AppConfig, llm: MeteredLLMClient,
                            gateway: NotionGateway,
                            known: Optional[list[Item]] = None) -> Item:
    """Re-run interpretation after a rejection, feeding the reviewer notes back in
    as added context (spec §9.2). Rejected → Awaiting Interpretation → Draft."""
    sm.assert_transition(item.status, ItemStatus.CLASS_A_AWAITING_INTERPRETATION,
                         sm.Actor.HUMAN)
    item.status = ItemStatus.CLASS_A_AWAITING_INTERPRETATION
    item = interpret_mod.interpret(item, cfg, llm, known=known)
    sm.assert_transition(item.status, ItemStatus.CLASS_A_DRAFT_INTERPRETATION,
                         sm.Actor.PIPELINE)
    item.status = ItemStatus.CLASS_A_DRAFT_INTERPRETATION
    gateway.upsert_item(item)
    return item


def escalate(item: Item, senior_reviewer: str, gateway: NotionGateway) -> Item:
    """Escalate a draft to a senior reviewer / external counsel (reassignment;
    the Item stays in review)."""
    item.reviewer = senior_reviewer
    note = "[escalated] " + (item.review_notes or "")
    item.review_notes = note.strip()
    gateway.upsert_item(item)
    get_alerter().fire(AlertLevel.INFO, f"Interpretation escalated to {senior_reviewer}",
                       item_id=item.page_id)
    return item


# --------------------------------------------------------------------------- #
# WF3 — client-impact & action planning (Story 8.3)
# --------------------------------------------------------------------------- #
_ACTION_TERMINAL = {"No action", "Done"}


def set_client_action(item: Item, action_status: str, gateway: NotionGateway,
                      *, owner: Optional[str] = None, deadline=None,
                      now: Optional[datetime] = None) -> Item:
    """Record a Client Action Status on an Approved Item. Terminal statuses
    archive the Item; actionable ones move it to Requires Action."""
    item.client_action_status = action_status
    if owner is not None:
        item.action_owner = owner
    if deadline is not None:
        item.action_deadline = deadline
    target = (ItemStatus.ARCHIVED if action_status in _ACTION_TERMINAL
              else ItemStatus.REQUIRES_ACTION)
    if item.status is not target:
        sm.assert_transition(item.status, target, sm.Actor.HUMAN)
        item.status = target
    if action_status == "Track Deadline":
        track_deadline(item)
    gateway.upsert_item(item)
    return item


def track_deadline(item: Item) -> Optional[str]:
    """Schedule a reminder before the entry-into-force / action deadline. MVP
    dispatches through the alerting hook (pluggable to calendar later)."""
    deadline = None
    if item.interpretation and item.interpretation.entry_into_force:
        deadline = item.interpretation.entry_into_force
    elif item.action_deadline:
        deadline = item.action_deadline.isoformat()
    if not deadline:
        return None
    get_alerter().fire(AlertLevel.INFO,
                       f"Deadline reminder scheduled for {deadline}",
                       item_id=item.page_id, deadline=str(deadline))
    return str(deadline)


# --------------------------------------------------------------------------- #
# Bidirectional edits & B→A reclassify (Story 8.4, FR-18/22, AD-11)
# --------------------------------------------------------------------------- #
def apply_reviewer_edit(item: Item, changes: dict, gateway: NotionGateway) -> Item:
    """Reflect a reviewer's Notion edits back into the system. A status change is
    validated against the state machine (HUMAN) before applying; illegal
    transitions raise rather than silently applying (AD-6)."""
    new_status = changes.pop("status", None)
    if new_status is not None:
        dst = ItemStatus(new_status)
        sm.assert_transition(item.status, dst, sm.Actor.HUMAN)
        item.status = dst
    for field, value in changes.items():
        if not hasattr(item, field):
            raise PermanentError(f"Unknown Item field in reviewer edit: {field}")
        setattr(item, field, value)
    gateway.upsert_item(item)
    return item


def reclassify_b_to_a(item: Item, refetch: Callable[[str], str],
                      gateway: NotionGateway, *,
                      cfg: Optional[AppConfig] = None,
                      llm: Optional[MeteredLLMClient] = None,
                      known: Optional[list[Item]] = None) -> Item:
    """B→A reclassify (FR-22, AD-11): re-fetch full text from the source URL and
    hydrate it IN PLACE on the existing Item id — never mint a new Item, even if
    the re-extracted hash differs — then enqueue interpretation. If cfg+llm are
    given, interpret immediately; otherwise leave it Awaiting Interpretation."""
    if item.content_class is not ContentClass.B:
        raise PermanentError(f"reclassify_b_to_a expects Class B, got {item.content_class}")
    from ..core.models import text_hash

    text = refetch(item.url)
    page_id = item.page_id  # preserved across the write → no new Item (AD-14)
    item.full_text = text
    item.snippet = text[:500] if text else None
    item.hash = text_hash(text or item.title)
    item.content_class = ContentClass.A
    item.reclassify_requested = False
    item.reclassified_from_b = True  # for the reclassification-rate metric (<5%)
    sm.assert_transition(item.status, ItemStatus.CLASS_A_AWAITING_INTERPRETATION,
                         sm.Actor.HUMAN)
    item.status = ItemStatus.CLASS_A_AWAITING_INTERPRETATION

    if cfg is not None and llm is not None:
        item = interpret_mod.interpret(item, cfg, llm, known=known)
        item.status = ItemStatus.CLASS_A_DRAFT_INTERPRETATION

    item.page_id = page_id
    gateway.upsert_item(item)
    _log.log(source="reclassify", event="b_to_a", status=item.status.value,
             item_id=item.page_id)
    return item
