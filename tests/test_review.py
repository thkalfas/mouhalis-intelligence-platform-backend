"""Epic 8 — human review workflows (WF1/WF2/WF3), edits, and B→A reclassify."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.errors import IllegalTransition, PermanentError
from legal_intel.core.llm_client import FakeLLMBackend, MeteredLLMClient
from legal_intel.core.models import (ContentClass, Interpretation, Item,
                                     ItemStatus)
from legal_intel.core.notion_gateway import LocalJSONBackend, NotionGateway
from legal_intel.pipeline import review as RV
from legal_intel.pipeline.runner import phase0_responder
from legal_intel.platform.cost_ledger import CostLedger

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    reload_config()
    return load_config()


def _gw():
    return NotionGateway(LocalJSONBackend())


def _interp():
    return Interpretation(summary="s", what_changed_before="b", what_changed_after="a",
                          what_changed_delta="d")


def _item(**kw) -> Item:
    base = dict(source_id="s1", source_name="EUR-Lex", title="Τίτλος", type="Regulation",
                authority="EU", date_published=date(2026, 7, 8), url="https://x/1",
                full_text="κείμενο", page_id="p1", collected_at=_NOW)
    base.update(kw)
    return Item(**base)


# --------------------------------------------------------------------------- #
# Assignment
# --------------------------------------------------------------------------- #
def test_assign_prefers_expertise_then_least_loaded():
    item = _item(topics=["gdpr_direct_marketing"])
    reviewers = [
        {"name": "Maria", "expertise": ["food_labeling"], "queue_depth": 1},
        {"name": "Nikos", "expertise": ["gdpr_direct_marketing"], "queue_depth": 5},
        {"name": "Eleni", "expertise": [], "queue_depth": 0},
    ]
    assert RV.assign_reviewer(item, reviewers) == "Nikos"  # expertise wins over load


def test_assign_falls_back_to_least_loaded_when_no_expert():
    item = _item(topics=["csrd_scope"])
    reviewers = [{"name": "A", "expertise": [], "queue_depth": 3},
                 {"name": "B", "expertise": [], "queue_depth": 1}]
    assert RV.assign_reviewer(item, reviewers) == "B"


# --------------------------------------------------------------------------- #
# WF1 — Class C relevance review
# --------------------------------------------------------------------------- #
def test_wf1_classify_as_a_promotes():
    gw = _gw()
    item = _item(content_class=ContentClass.C,
                 status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW)
    out = RV.relevance_review(item, "A", "Maria", gw, reason="sector match", now=_NOW)
    assert out.content_class is ContentClass.A
    assert out.status is ItemStatus.CLASS_A_AWAITING_INTERPRETATION
    assert out.reviewer == "Maria" and out.class_c_decided_at == _NOW


def test_wf1_classify_as_b_downgrades_and_purges():
    gw = _gw()
    item = _item(content_class=ContentClass.C,
                 status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW)
    out = RV.relevance_review(item, "B", "Nikos", gw, now=_NOW)
    assert out.content_class is ContentClass.B
    assert out.full_text is None


# --------------------------------------------------------------------------- #
# WF2 — interpretation review + feedback
# --------------------------------------------------------------------------- #
def test_wf2_approve_as_is():
    gw = _gw()
    item = _item(content_class=ContentClass.A,
                 status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION, interpretation=_interp())
    out = RV.approve_interpretation(item, "Maria", gw, now=_NOW)
    assert out.status is ItemStatus.APPROVED
    assert out.review_feedback == {}          # approved without edits


def test_wf2_edit_and_approve_captures_diff():
    gw = _gw()
    item = _item(content_class=ContentClass.A,
                 status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION, interpretation=_interp())
    edited = _interp()
    edited.summary = "διορθωμένη σύνοψη"
    out = RV.edit_and_approve(item, edited, "Maria", gw, now=_NOW)
    assert out.status is ItemStatus.APPROVED
    assert "summary" in out.review_feedback
    assert out.review_feedback["summary"]["to"] == "διορθωμένη σύνοψη"


def test_wf2_reject_then_regenerate(cfg):
    gw = _gw()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=phase0_responder),
                           sink=CostLedger())
    item = _item(content_class=ContentClass.A,
                 status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION, interpretation=_interp(),
                 topics=["tobacco_traceability"])
    RV.reject_and_redo(item, "Λείπει η ανάλυση κόστους", "Maria", gw, now=_NOW)
    assert item.status is ItemStatus.REJECTED
    assert item.review_notes == "Λείπει η ανάλυση κόστους"

    out = RV.regenerate_after_reject(item, cfg, llm, gw)
    assert out.status is ItemStatus.CLASS_A_DRAFT_INTERPRETATION
    assert out.interpretation is not None


def test_wf2_sla_fast_track_for_immediate():
    assert RV.wf2_sla(_item(action_signal="immediate")) == {"hours": 24}
    assert RV.wf2_sla(_item(action_signal="monitor")) == {"business_days": 3}


# --------------------------------------------------------------------------- #
# WF3 — client-impact & action planning
# --------------------------------------------------------------------------- #
def test_wf3_track_deadline_moves_to_requires_action_and_reminds():
    gw = _gw()
    interp = _interp()
    interp.entry_into_force = "2026-09-01"
    item = _item(content_class=ContentClass.A, status=ItemStatus.APPROVED,
                 interpretation=interp)
    out = RV.set_client_action(item, "Track Deadline", gw, owner="Compliance", now=_NOW)
    assert out.status is ItemStatus.REQUIRES_ACTION
    assert out.client_action_status == "Track Deadline"
    assert out.action_owner == "Compliance"


def test_wf3_no_action_archives():
    gw = _gw()
    item = _item(content_class=ContentClass.A, status=ItemStatus.APPROVED,
                 interpretation=_interp())
    out = RV.set_client_action(item, "No action", gw)
    assert out.status is ItemStatus.ARCHIVED


# --------------------------------------------------------------------------- #
# 8.4 — bidirectional edits + B→A reclassify
# --------------------------------------------------------------------------- #
def test_apply_reviewer_edit_validates_status_transition():
    gw = _gw()
    item = _item(content_class=ContentClass.A,
                 status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION, interpretation=_interp())
    out = RV.apply_reviewer_edit(item, {"status": "Class A - Approved",
                                        "review_notes": "ok"}, gw)
    assert out.status is ItemStatus.APPROVED
    assert out.review_notes == "ok"


def test_apply_reviewer_edit_rejects_illegal_transition():
    gw = _gw()
    item = _item(content_class=ContentClass.B, status=ItemStatus.CLASS_B_INDEXED)
    with pytest.raises(IllegalTransition):
        RV.apply_reviewer_edit(item, {"status": "Class A - Approved"}, gw)


def test_reclassify_b_to_a_hydrates_in_place_same_page():
    gw = _gw()
    item = _item(content_class=ContentClass.B, status=ItemStatus.CLASS_B_INDEXED,
                 full_text=None, snippet=None, hash="oldhash", reclassify_requested=True)
    gw.upsert_item(item)
    before = gw.count()

    out = RV.reclassify_b_to_a(item, refetch=lambda url: "νέο πλήρες κείμενο", gateway=gw)
    assert out.content_class is ContentClass.A
    assert out.status is ItemStatus.CLASS_A_AWAITING_INTERPRETATION
    assert out.full_text == "νέο πλήρες κείμενο"
    assert out.reclassified_from_b is True
    assert out.page_id == "p1"
    assert gw.count() == before                 # no new Item minted (AD-11/14)


def test_reclassify_can_interpret_immediately(cfg):
    gw = _gw()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=phase0_responder),
                           sink=CostLedger())
    item = _item(content_class=ContentClass.B, status=ItemStatus.CLASS_B_INDEXED,
                 full_text=None, topics=["tobacco_traceability"])
    gw.upsert_item(item)
    out = RV.reclassify_b_to_a(item, refetch=lambda url: "κείμενο ΚΑΔ 46.35",
                               gateway=gw, cfg=cfg, llm=llm)
    assert out.status is ItemStatus.CLASS_A_DRAFT_INTERPRETATION
    assert out.interpretation is not None


def test_reclassify_rejects_non_b():
    gw = _gw()
    item = _item(content_class=ContentClass.A, status=ItemStatus.APPROVED)
    with pytest.raises(PermanentError):
        RV.reclassify_b_to_a(item, refetch=lambda url: "x", gateway=gw)
