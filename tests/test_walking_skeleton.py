"""End-to-end fake-data walking skeleton (Story 0.9) — the Phase-0 gate.

Proves a fake Legal Event traverses the full pipeline into Notion with the
correct class-aware payloads, that dedup merges cross-source duplicates, that
retention follows Content Class, and that re-running is idempotent (AD-4).
"""
from __future__ import annotations

from legal_intel.adapters.fake import FakeSourceAdapter
from legal_intel.core.models import ContentClass, Item, ItemStatus


def _items(gateway) -> list[Item]:
    return [Item.model_validate(p) for p in gateway.all_items()]


def test_end_to_end_classes_and_dedup(runner, gateway):
    report = runner.run(FakeSourceAdapter())

    # 4 fake records in; the kodiko duplicate merges into the EUR-Lex item → 3 Items.
    assert report.ingested == 4
    assert gateway.count() == 3

    items = _items(gateway)
    by_class = {i.content_class for i in items}
    assert by_class == {ContentClass.A, ContentClass.B, ContentClass.C}


def test_class_aware_retention(runner, gateway):
    runner.run(FakeSourceAdapter())
    items = {i.content_class: i for i in _items(gateway)}

    b = items[ContentClass.B]
    assert b.full_text is None and b.snippet is None  # AD-5: no full text for B
    assert b.status is ItemStatus.CLASS_B_INDEXED

    c = items[ContentClass.C]
    assert c.full_text  # transient full text held for review
    assert c.status is ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW


def test_class_a_has_validated_interpretation(runner, gateway):
    runner.run(FakeSourceAdapter())
    a = {i.content_class: i for i in _items(gateway)}[ContentClass.A]

    assert a.status is ItemStatus.CLASS_A_DRAFT_INTERPRETATION
    assert a.interpretation is not None
    assert a.interpretation.actions_required  # structured actions present
    assert "νομική συμβουλή" in a.interpretation.disclaimer  # not-legal-advice
    # dedup merge preserved the lower-authority source link + its commentary
    assert any(s.source == "kodiko.gr" for s in a.additional_sources)
    assert a.external_commentary


def test_class_reasoning_envelope(runner, gateway):
    runner.run(FakeSourceAdapter())
    items = {i.content_class: i for i in _items(gateway)}
    # Class A here was decided by the deterministic KAD rule.
    a = items[ContentClass.A]
    assert a.class_reasoning.decided_by.value == "rule"
    assert a.class_reasoning.rule_id == "kad_direct_mention"
    # Class C was decided by the LLM classifier.
    c = items[ContentClass.C]
    assert c.class_reasoning.decided_by.value == "llm"


def test_rerun_is_idempotent(runner, gateway):
    first = runner.run(FakeSourceAdapter())
    count_after_first = gateway.count()

    second = runner.run(FakeSourceAdapter())
    # No new Items on the second pass — upsert-by-key + dedup hold (AD-4, AD-14).
    assert gateway.count() == count_after_first == 3
    # Second pass reclassifies nothing (already-classified items are skipped).
    assert second.by_class == {} or all(
        v == first.by_class.get(k) for k, v in second.by_class.items()
    )


def test_run_isolates_unexpected_exception(runner):
    # A non-PermanentError (e.g. a transient network error) mid-item must skip
    # just that item and be recorded — never crash the whole run (AD-12).
    def _boom(record, known):
        raise RuntimeError("boom")

    runner._process = _boom
    report = runner.run(FakeSourceAdapter())
    assert report.ingested == 4
    assert report.errors == 4 and report.persisted == 0  # all isolated, none fatal
    assert all("boom" in reason for _sid, reason in report.error_details)


def test_cost_ledger_records_llm_calls(runner, gateway, ledger):
    runner.run(FakeSourceAdapter())
    # Two LLM classifier calls (maritime, ambiguous) + one interpretation call.
    stages = {r.stage for r in ledger.rows}
    assert "relevance_classify" in stages
    assert "interpretation" in stages
    report = ledger.monthly_report()
    assert report["calls"] >= 3
    assert report["failed_call_rate"] == 0.0
