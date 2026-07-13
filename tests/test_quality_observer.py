"""Epic 8 Story 8.5 — Quality Observer metrics & thresholds."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from legal_intel.agents.quality_observer import (QualityObserver,
                                                 business_days_between)
from legal_intel.core.models import ContentClass, Item, ItemStatus
from legal_intel.platform.cost_ledger import CostLedger

_MON = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)  # a Monday


def _item(cls, status=ItemStatus.NEW, **kw) -> Item:
    base = dict(source_id="s", source_name="EUR-Lex", title="t", type="Regulation",
                authority="EU", date_published=date(2026, 7, 1), url="https://x",
                content_class=cls, status=status, topics=["food_labeling"])
    base.update(kw)
    return Item(**base)


def test_business_days_between():
    # Monday → Thursday = 3 business days; spanning a weekend excludes it.
    assert business_days_between(_MON, _MON + timedelta(days=3)) == 3
    assert business_days_between(_MON, _MON + timedelta(days=7)) == 5  # skips Sat/Sun


def test_class_c_rate_and_coverage():
    items = [_item(ContentClass.A), _item(ContentClass.B), _item(ContentClass.C),
             _item(ContentClass.C)]
    retro = QualityObserver().run(items, CostLedger(), now=_MON)
    m = {x.key: x.value for x in retro.metrics}
    assert m["class_c_rate"] == 0.5
    assert m["tagging_coverage"] == 1.0   # all have a topic


def test_high_class_c_rate_breaches():
    items = [_item(ContentClass.C) for _ in range(3)] + [_item(ContentClass.A)]
    retro = QualityObserver().run(items, CostLedger(), now=_MON)
    assert any("class_c_rate" in b for b in retro.breaches)  # 0.75 > 0.25


def test_reclassification_rate():
    items = [_item(ContentClass.B), _item(ContentClass.B),
             _item(ContentClass.A, reclassified_from_b=True)]
    retro = QualityObserver().run(items, CostLedger(), now=_MON)
    m = {x.key: x.value for x in retro.metrics}
    # 1 reclassified / (2 current B + 1 reclassified) = 0.3333
    assert m["reclassification_b_to_a_rate"] == round(1 / 3, 4)


def test_approval_without_edits_and_time_to_approval():
    approved_clean = _item(ContentClass.A, status=ItemStatus.APPROVED,
                           draft_created_at=_MON,
                           review_completed_at=_MON + timedelta(days=1))
    approved_edited = _item(ContentClass.A, status=ItemStatus.APPROVED,
                            draft_created_at=_MON,
                            review_completed_at=_MON + timedelta(days=1),
                            review_feedback={"summary": {"from": "a", "to": "b"}})
    retro = QualityObserver().run([approved_clean, approved_edited], CostLedger(), now=_MON)
    m = {x.key: x.value for x in retro.metrics}
    assert m["approval_without_edits_rate"] == 0.5
    assert m["median_days_to_approval"] == 1


def test_relevance_sla_compliance():
    on_time = _item(ContentClass.A, class_c_assigned_at=_MON,
                    class_c_decided_at=_MON + timedelta(days=1))
    late = _item(ContentClass.B, class_c_assigned_at=_MON,
                 class_c_decided_at=_MON + timedelta(days=6))  # spans weekend, >2 bd
    retro = QualityObserver().run([on_time, late], CostLedger(), now=_MON)
    m = {x.key: x.value for x in retro.metrics}
    assert m["sla_relevance_compliance"] == 0.5


def test_optional_llm_narrative():
    from legal_intel.core.llm_client import FakeLLMBackend, MeteredLLMClient
    led = CostLedger()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: "Καλή εβδομάδα."),
                           sink=led)
    retro = QualityObserver().run([_item(ContentClass.A)], led, now=_MON, llm=llm)
    assert retro.narrative == "Καλή εβδομάδα."
    assert any(r.stage == "quality_observer" for r in led.rows)
