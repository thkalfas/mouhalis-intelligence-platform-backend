"""Unit tests for the V2 sink's item -> payload projection.

Covers only the pure mapping (`item_to_payload`). The `V2Sink.publish` side —
Postgres upsert + event_clients seeding — is an integration concern and runs
against a real DB elsewhere.
"""
from __future__ import annotations

from datetime import date

from legal_intel.core.models import (
    ClassReasoning,
    ContentClass,
    DecidedBy,
    Interpretation,
    Item,
    ItemStatus,
)
from legal_intel.platform.v2_sink import item_to_payload


def _item(**overrides) -> Item:
    base = dict(
        source_id="123",
        source_name="fek",
        title="Test law",
        type="law",
        authority="Υπουργείο Οικονομικών",
        content_class=ContentClass.A,
        status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION,
        topics=["energy", "renewables"],
        date_published=date(2026, 10, 30),
        url="https://et.gr/doc/1",
        snippet="snippet fallback",
    )
    base.update(overrides)
    return Item(**base)


def test_classified_item_maps_core_fields():
    item = _item()
    payload = item_to_payload(item)
    assert payload is not None
    assert payload.external_id == "fek::123"
    assert payload.title == "Test law"
    assert payload.source == "fek"
    assert payload.source_url == "https://et.gr/doc/1"
    assert payload.published_on == "2026-10-30"
    assert payload.event_type == "law"
    assert payload.topics == ["energy", "renewables"]


def test_unclassified_item_is_filtered():
    item = _item(content_class=None, status=ItemStatus.AWAITING_TRIAGE)
    assert item_to_payload(item) is None


def test_rejected_and_archived_items_are_filtered():
    for st in (ItemStatus.REJECTED, ItemStatus.ARCHIVED, ItemStatus.SUPERSEDED):
        assert item_to_payload(_item(status=st)) is None


def test_awaiting_interpretation_is_filtered_too():
    # Pipeline knows it's Class A but hasn't produced the interpretation yet,
    # so it's not ready for V2. V2 would otherwise show it with no summary.
    item = _item(status=ItemStatus.CLASS_A_AWAITING_INTERPRETATION)
    assert item_to_payload(item) is None


def test_interpretation_summary_wins_over_snippet():
    item = _item(
        interpretation=Interpretation(
            summary="Full interpretation summary.",
            what_changed_before="",
            what_changed_after="",
            what_changed_delta="",
        ),
    )
    payload = item_to_payload(item)
    assert payload is not None
    assert payload.summary == "Full interpretation summary."


def test_falls_back_to_snippet_when_no_interpretation():
    item = _item(interpretation=None, snippet="only the snippet")
    payload = item_to_payload(item)
    assert payload is not None
    assert payload.summary == "only the snippet"


def test_empty_summary_when_no_source_text():
    item = _item(interpretation=None, snippet=None)
    payload = item_to_payload(item)
    assert payload is not None
    assert payload.summary == ""


def test_null_date_maps_to_none():
    item = _item(date_published=None)
    payload = item_to_payload(item)
    assert payload is not None
    assert payload.published_on is None


def test_class_b_is_published_too():
    item = _item(
        content_class=ContentClass.B,
        status=ItemStatus.CLASS_B_INDEXED,
        class_reasoning=ClassReasoning(decided_by=DecidedBy.RULE, detail="x"),
    )
    payload = item_to_payload(item)
    assert payload is not None
    assert payload.external_id == "fek::123"


def test_class_c_is_published_too():
    item = _item(
        content_class=ContentClass.C,
        status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW,
    )
    assert item_to_payload(item) is not None
