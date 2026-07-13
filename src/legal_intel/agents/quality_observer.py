"""Quality Observer agent (Story 8.5, FR-20, spec §9.4/§9.5).

A scheduled (weekly) agent that computes the system-health metrics SM-1..SM-7
plus counter-metrics over the current Item set and the cost ledger, flags any
past its alert threshold, and produces a retro summary. Metric computation is
deterministic; an optional metered LLM call can add a narrative. Runs read-only
over the store — it observes, it does not mutate Items.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Optional

from ..core.llm_client import MeteredLLMClient
from ..core.models import ContentClass, Item, ItemStatus
from ..pipeline.tag import tagging_coverage
from ..platform.alerting import AlertLevel, get_alerter
from ..platform.cost_ledger import CostLedger


def business_days_between(start: datetime, end: datetime) -> int:
    """Whole business days elapsed from ``start`` to ``end`` (weekends excluded)."""
    if end <= start:
        return 0
    days = 0
    cur = start.date()
    end_date = end.date()
    while cur < end_date:
        cur = cur.fromordinal(cur.toordinal() + 1)
        if cur.weekday() < 5:  # Mon-Fri
            days += 1
    return days


@dataclass
class Metric:
    key: str
    value: Optional[float]
    target: str
    breached: bool = False


@dataclass
class Retro:
    metrics: list[Metric] = field(default_factory=list)
    breaches: list[str] = field(default_factory=list)
    narrative: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "metrics": {m.key: m.value for m in self.metrics},
            "breaches": self.breaches,
            "narrative": self.narrative,
        }


def _rate(numer: int, denom: int) -> Optional[float]:
    return round(numer / denom, 4) if denom else None


class QualityObserver:
    def __init__(self, cfg=None) -> None:
        self.cfg = cfg
        self.log = get_alerter()

    def run(self, items: list[Item], ledger: CostLedger, *,
            now: Optional[datetime] = None,
            llm: Optional[MeteredLLMClient] = None) -> Retro:
        now = now or datetime.now(timezone.utc)
        metrics: list[Metric] = []
        breaches: list[str] = []

        def add(key, value, target, breached):
            metrics.append(Metric(key, value, target, breached))
            if breached and value is not None:
                breaches.append(f"{key}={value} ({target})")

        total = len(items)
        class_c = [i for i in items if i.content_class is ContentClass.C]
        class_b = [i for i in items if i.content_class is ContentClass.B]

        # SM-1 Class C rate — target <15%, alert >25%
        c_rate = _rate(len(class_c), total)
        add("class_c_rate", c_rate, "<0.15 (alert >0.25)",
            c_rate is not None and c_rate > 0.25)

        # SM-2 approval-without-edits rate — target >40%, alert <20%
        _approved_states = (ItemStatus.APPROVED, ItemStatus.REQUIRES_ACTION,
                            ItemStatus.ARCHIVED)
        approved = [i for i in items if i.review_completed_at is not None
                    and i.status in _approved_states]
        without_edits = [i for i in approved if not i.review_feedback]
        awe = _rate(len(without_edits), len(approved))
        add("approval_without_edits_rate", awe, ">0.40 (alert <0.20)",
            awe is not None and awe < 0.20)

        # SM-3 median business days to interpretation approval — alert >5
        durations = [business_days_between(i.draft_created_at, i.review_completed_at)
                     for i in approved
                     if i.draft_created_at and i.review_completed_at]
        med = round(median(durations), 2) if durations else None
        add("median_days_to_approval", med, "<3 (alert >5)",
            med is not None and med > 5)

        # SM-4 reclassification B→A rate — target <5%, alert >10%
        reclassified = [i for i in items if i.reclassified_from_b]
        ever_b = len(class_b) + len(reclassified)
        recl = _rate(len(reclassified), ever_b)
        add("reclassification_b_to_a_rate", recl, "<0.05 (alert >0.10)",
            recl is not None and recl > 0.10)

        # SM-5 SLA — relevance review within 2 business days — alert <80%
        decided_c = [i for i in items if i.class_c_assigned_at and i.class_c_decided_at]
        within = [i for i in decided_c
                  if business_days_between(i.class_c_assigned_at, i.class_c_decided_at) <= 2]
        sla_rel = _rate(len(within), len(decided_c))
        add("sla_relevance_compliance", sla_rel, ">0.90 (alert <0.80)",
            sla_rel is not None and sla_rel < 0.80)

        # SM-6 SLA — interpretation review within SLA (24h immediate else 3 bd) — alert <75%
        reviewed = [i for i in approved if i.draft_created_at and i.review_completed_at]
        def _within_interp_sla(i: Item) -> bool:
            if i.action_signal == "immediate":
                return (i.review_completed_at - i.draft_created_at).total_seconds() <= 24 * 3600
            return business_days_between(i.draft_created_at, i.review_completed_at) <= 3
        sla_int = _rate(sum(1 for i in reviewed if _within_interp_sla(i)), len(reviewed))
        add("sla_interpretation_compliance", sla_int, ">0.85 (alert <0.75)",
            sla_int is not None and sla_int < 0.75)

        # SM-7 reviewer workload balance = max/mean — alert >2.0
        loads: dict[str, int] = {}
        for i in items:
            if i.reviewer and i.status in (ItemStatus.CLASS_A_DRAFT_INTERPRETATION,
                                           ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW):
                loads[i.reviewer] = loads.get(i.reviewer, 0) + 1
        balance = None
        if loads:
            vals = list(loads.values())
            mean = sum(vals) / len(vals)
            balance = round(max(vals) / mean, 2) if mean else None
        add("reviewer_workload_balance", balance, "<1.5 (alert >2.0)",
            balance is not None and balance > 2.0)

        # Counter-metric: tagging coverage — target >95%, alert <90%
        cov = round(tagging_coverage(items), 4)
        add("tagging_coverage", cov, ">0.95 (alert <0.90)", cov < 0.90)

        # Cost health (reuses the ledger's own thresholds/alerts).
        report = ledger.monthly_report()

        for b in breaches:
            get_alerter().fire(AlertLevel.WARNING, f"Quality metric breach: {b}")

        narrative = None
        if llm is not None:
            import json
            res = llm.complete(
                stage="quality_observer",
                model=(self.cfg.interpretation.default_model if self.cfg else "claude-sonnet"),
                system="Summarize the week's legal-intel pipeline health in Greek, 3-4 sentences.",
                prompt=json.dumps({"metrics": {m.key: m.value for m in metrics},
                                   "breaches": breaches, "cost": report}, ensure_ascii=False),
            )
            narrative = res.text

        return Retro(metrics=metrics, breaches=breaches, narrative=narrative)
