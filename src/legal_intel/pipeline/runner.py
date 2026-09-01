"""Pipeline runner — the composition root that wires the filters (AD-1).

Drives fetched Source Records through: normalize → dedup → tag → triage →
(Class A) interpret, advancing the Item's status via the state machine
(Actor.PIPELINE only) and persisting through the NotionGateway at each step.
Failure isolates per item (AD-12); already-classified items are skipped on
re-runs so the whole run is idempotent (AD-4) and cost is not re-incurred.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..adapters.base import SourceAdapter
from ..core import state_machine as sm
from ..core.config import AppConfig, load_config
from ..core.errors import PermanentError
from ..core.llm_client import FakeLLMBackend, MeteredLLMClient, make_backend
from ..core.models import ContentClass, Item, ItemStatus
from ..core.notion_gateway import NotionGateway
from ..platform.alerting import AlertLevel, get_alerter
from ..platform.cost_ledger import CostLedger
from ..platform.logging import get_logger
from . import dedup as dedup_mod
from . import interpret as interpret_mod
from . import normalize as normalize_mod
from . import tag as tag_mod
from . import triage as triage_mod


# --------------------------------------------------------------------------- #
# Phase-0 deterministic fake LLM responder (Story 0.9). In production the
# MeteredLLMClient uses the real Anthropic/Agent-SDK backend instead.
# --------------------------------------------------------------------------- #
def phase0_responder(stage: str, prompt: str) -> str:
    p = prompt.lower()
    if stage == "topic_tag":
        # Phase-0 tagger is a no-op (rule-based tagging already covers the fake
        # fixtures); real topic proposals come from the Anthropic backend.
        return json.dumps({"topics": []})
    if stage == "relevance_classify":
        if "ναυτ" in p or "maritime" in p or "λιμ" in p:
            return json.dumps({"relevance": "low", "confidence": 0.95,
                               "reasoning": "Αφορά ναυτιλιακά/λιμενικά — εκτός πεδίου δραστηριότητας.",
                               "sector_touchpoints": ["none"], "action_signal": "none",
                               "specialist_needed": False})
        return json.dumps({"relevance": "medium", "confidence": 0.6,
                           "reasoning": "Πιθανή σχετικότητα με επισήμανση προϊόντων — χρειάζεται ανθρώπινη κρίση.",
                           "sector_touchpoints": ["food_wholesale"], "action_signal": "monitor",
                           "specialist_needed": False})
    if stage == "interpretation":
        return json.dumps({
            "summary": "Νέες υποχρεώσεις που ενδέχεται να επηρεάζουν τη δραστηριότητα του πελάτη.",
            "what_changed_before": "Προηγούμενο καθεστώς χωρίς τη συγκεκριμένη υποχρέωση.",
            "what_changed_after": "Θεσπίζεται νέα υποχρέωση.",
            "what_changed_delta": "Προστίθεται υποχρέωση καταγραφής/συμμόρφωσης.",
            "business_lines_affected": ["tobacco_wholesale"],
            "support_functions_affected": ["legal", "compliance"],
            "operational_impact": "Απαιτείται προσαρμογή διαδικασιών.",
            "compliance_new_obligations": ["Καταγραφή μετακινήσεων προϊόντος."],
            "actions_required": [{
                "action": "Ενημέρωση εσωτερικής διαδικασίας ιχνηλασιμότητας.",
                "owner_role": "Head of Compliance",
                "deadline": "2026-12-31",
                "priority": "high",
                "estimated_effort": "medium",
            }],
            "entry_into_force": "2026-09-01",
            "cited_articles": ["Άρθρο 3"],
            "confidence_notes": "Η ερμηνεία βασίζεται σε πρώτη ανάγνωση.",
            "requires_specialist_review": False,
            "_self_confidence": 0.72,
        }, ensure_ascii=False)
    return json.dumps({"stub": True, "stage": stage})


@dataclass
class RunReport:
    ingested: int = 0
    persisted: int = 0
    skipped: int = 0
    filtered: int = 0  # skipped by the lookback window (too old)
    errors: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    error_details: list[tuple[str, str]] = field(default_factory=list)  # (source_id, reason)


class PipelineRunner:
    def __init__(self, cfg: Optional[AppConfig] = None,
                 gateway: Optional[NotionGateway] = None,
                 llm: Optional[MeteredLLMClient] = None,
                 ledger: Optional[CostLedger] = None) -> None:
        self.cfg = cfg or load_config()
        self.gateway = gateway or NotionGateway()
        self.ledger = ledger or CostLedger()
        self.llm = llm or MeteredLLMClient(backend=self._default_backend(),
                                           sink=self.ledger)
        self.log = get_logger()

    @staticmethod
    def _default_backend():
        """Honor LEGAL_INTEL_LLM_BACKEND: real Claude when 'anthropic', otherwise
        the deterministic offline fake (canned but schema-valid output, so the
        skeleton and tests run with no key). An explicitly injected llm wins."""
        if os.environ.get("LEGAL_INTEL_LLM_BACKEND", "fake").lower() == "anthropic":
            return make_backend()  # AnthropicBackend (reads ANTHROPIC_API_KEY)
        return FakeLLMBackend(responder=phase0_responder)

    def _known_items(self) -> list[Item]:
        """Reconstruct known Items from the gateway so dedup/idempotency survive
        across runs (AD-14). Corrupt payloads are skipped, not fatal."""
        out: list[Item] = []
        for payload in self.gateway.all_items():
            try:
                out.append(Item.model_validate(payload))
            except Exception:  # pragma: no cover - defensive
                continue
        return out

    def _transition(self, item: Item, dst: ItemStatus) -> None:
        sm.assert_transition(item.status, dst, sm.Actor.PIPELINE)
        item.status = dst

    def _too_old(self, record, today: date) -> bool:
        """Lookback window (config max_age_days): skip Items published before the
        cutoff. 0 disables it; undated records always pass."""
        max_age = self.cfg.max_age_days
        if not max_age or record.date_published is None:
            return False
        return record.date_published < today - timedelta(days=max_age)

    def run(self, adapter: SourceAdapter, now: Optional[date] = None) -> RunReport:
        report = RunReport()
        known = self._known_items()
        today = now or datetime.now(timezone.utc).date()

        for record in adapter.fetch():
            report.ingested += 1
            if self._too_old(record, today):
                report.filtered += 1
                self.log.log(source=adapter.name, event="filtered",
                             status="too_old", item_id=record.source_id,
                             error=f"older than {self.cfg.max_age_days}d")
                continue
            try:
                item = self._process(record, known)
            except Exception as exc:  # isolate ANY item failure (AD-12) — a
                # data-quality reject (PermanentError) OR a transient/network
                # error must skip just this item, never crash the whole run.
                report.errors += 1
                report.error_details.append((getattr(record, "source_id", "?"), str(exc)))
                self.log.log(source=adapter.name, event="process",
                             status="skipped", error=f"{type(exc).__name__}: {exc}")
                get_alerter().fire(AlertLevel.WARNING,
                                   f"Item skipped: {exc}", source=adapter.name,
                                   category="item_skip")  # digest-only, never Slack
                continue

            if item is None:  # already persisted, unchanged (idempotent skip)
                report.skipped += 1
                continue

            self.gateway.upsert_item(item)
            report.persisted += 1
            cls = item.content_class.value if item.content_class else "unclassified"
            report.by_class[cls] = report.by_class.get(cls, 0) + 1
            self.log.log(source=adapter.name, event="persisted",
                         status=item.status.value, item_id=item.page_id,
                         content_class=cls)
        return report

    def _reinterpret(self, item: Item, known: list[Item]) -> Item:
        """Re-run interpretation after a content-changing late merge (AD-16):
        route the Item back to Awaiting Interpretation for a fresh draft rather
        than mutating the existing (possibly Approved) reading in place."""
        self._transition(item, ItemStatus.CLASS_A_AWAITING_INTERPRETATION)
        item = interpret_mod.interpret(item, self.cfg, self.llm, known=known)
        self._transition(item, ItemStatus.CLASS_A_DRAFT_INTERPRETATION)
        return item

    def _process(self, record, known: list[Item]) -> Optional[Item]:
        item = normalize_mod.normalize(record)  # may raise PermanentError

        # Cross-run idempotency (AD-4): an identical re-fetch — same source + same
        # content hash → same upsert key — is already persisted. Skip it entirely:
        # no re-triage, no re-interpretation, no LLM cost. (A genuine content
        # change yields a new hash/key and is processed normally.)
        if self.gateway.exists(item.upsert_key()):
            self.log.log(source=record.source_name, event="process",
                         status="unchanged", item_id=record.source_id)
            return None

        outcome = dedup_mod.dedup(item, known, self.cfg)
        item = outcome.item
        if item not in known:
            known.append(item)

        # Superseding version (AD-15): retire the predecessor, then let the new
        # Item flow through triage/interpretation as fresh content.
        if outcome.superseded_target is not None:
            target = outcome.superseded_target
            if sm.can_transition(target.status, ItemStatus.SUPERSEDED, sm.Actor.PIPELINE):
                self._transition(target, ItemStatus.SUPERSEDED)
                self.gateway.upsert_item(target)
            else:
                self.log.log(source=record.source_name, event="supersede",
                             status="skipped", item_id=target.page_id,
                             error=f"cannot supersede from {target.status.value}")

        # Probable duplicate → human dedup-confirmation queue (AD-5).
        if outcome.needs_confirmation and item.content_class is None:
            self._transition(item, ItemStatus.AWAITING_DEDUP_CONFIRMATION)
            return item

        # Already classified (merged into an existing Item, or a prior run) →
        # normally skip re-triage/re-interpret (idempotent, cost-free; AD-4, AD-7),
        # unless the merge changed content of an interpreted Item (AD-16).
        if item.content_class is not None:
            if outcome.reinterpret and item.content_class is ContentClass.A:
                return self._reinterpret(item, known)
            return item

        # New item: triage decides the Content Class.
        self._transition(item, ItemStatus.AWAITING_TRIAGE)
        item = tag_mod.tag(item, self.cfg, self.llm)
        item = triage_mod.triage(item, self.cfg, self.llm)

        if item.content_class is ContentClass.A:
            self._transition(item, ItemStatus.CLASS_A_AWAITING_INTERPRETATION)
            item = interpret_mod.interpret(item, self.cfg, self.llm, known=known)  # AD-9
            self._transition(item, ItemStatus.CLASS_A_DRAFT_INTERPRETATION)
        elif item.content_class is ContentClass.B:
            self._transition(item, ItemStatus.CLASS_B_INDEXED)
        else:  # Class C
            self._transition(item, ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW)
        return item
