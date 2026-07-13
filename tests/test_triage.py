"""Epic 6 — relevance triage (Stories 6.1 rules, 6.2 LLM classifier, 6.3 retention)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.errors import PermanentError
from legal_intel.core.llm_client import FakeLLMBackend, MeteredLLMClient
from legal_intel.core.models import ContentClass, DecidedBy, Item, ItemStatus
from legal_intel.core.notion_gateway import LocalJSONBackend, NotionGateway
from legal_intel.pipeline import retention as R
from legal_intel.pipeline import triage as TR
from legal_intel.platform.cost_ledger import CostLedger

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    reload_config()
    return load_config()


def _item(*, title="", text="", topics=None, authority="EU",
          status=ItemStatus.AWAITING_TRIAGE, cls=None, collected=_NOW) -> Item:
    return Item(source_id="x", source_name="EUR-Lex", title=title, type="Regulation",
                authority=authority, date_published=date(2026, 7, 8), url="https://x",
                full_text=text or None, snippet=(text[:100] or None) if text else None,
                topics=topics or [], status=status, content_class=cls, collected_at=collected)


def _llm(responder):
    return MeteredLLMClient(backend=FakeLLMBackend(responder=responder), sink=CostLedger())


# --------------------------------------------------------------------------- #
# Story 6.1 — deterministic rules
# --------------------------------------------------------------------------- #
def test_kad_mention_forces_class_a(cfg):
    item = _item(title="Νόμος", text="Αφορά ΚΑΔ 46.35 χονδρικό εμπόριο καπνού")
    out = TR.triage(item, cfg, _llm(lambda s, p: "{}"))
    assert out.content_class is ContentClass.A
    assert out.class_reasoning.decided_by is DecidedBy.RULE
    assert out.class_reasoning.rule_id == "kad_direct_mention"


def test_high_priority_topic_forces_class_a(cfg):
    item = _item(title="x", topics=["food_recall"])
    out = TR.triage(item, cfg, _llm(lambda s, p: "{}"))
    assert out.content_class is ContentClass.A
    assert out.class_reasoning.rule_id == "high_priority_topic_hit"


def test_excluded_sector_forces_class_b(cfg):
    item = _item(title="Δασικά", topics=["forestry"])
    out = TR.triage(item, cfg, _llm(lambda s, p: "{}"))
    assert out.content_class is ContentClass.B
    assert out.class_reasoning.decided_by is DecidedBy.RULE
    assert out.class_reasoning.rule_id == "unrelated_sectors"


# --------------------------------------------------------------------------- #
# Story 6.2 — LLM classifier structured contract + threshold routing
# --------------------------------------------------------------------------- #
_VERDICT = ('{{"relevance": "{rel}", "confidence": {conf}, "reasoning": "λόγος", '
            '"sector_touchpoints": ["food_wholesale"], "action_signal": "immediate", '
            '"specialist_needed": true}}')


def test_llm_high_confidence_routes_to_a(cfg):
    item = _item(title="ασαφές")
    out = TR.triage(item, cfg, _llm(lambda s, p: _VERDICT.format(rel="high", conf=0.9)))
    assert out.content_class is ContentClass.A
    assert out.class_reasoning.decided_by is DecidedBy.LLM
    assert out.confidence_score == 0.9
    assert out.sector_touchpoints == ["food_wholesale"]
    assert out.action_signal == "immediate"
    assert out.specialist_needed is True


def test_llm_low_high_confidence_routes_to_b(cfg):
    item = _item(title="ασαφές")
    out = TR.triage(item, cfg, _llm(lambda s, p: _VERDICT.format(rel="low", conf=0.9)))
    assert out.content_class is ContentClass.B


def test_llm_medium_or_low_confidence_routes_to_c(cfg):
    medium = TR.triage(_item(title="ασαφές"), cfg,
                       _llm(lambda s, p: _VERDICT.format(rel="medium", conf=0.99)))
    assert medium.content_class is ContentClass.C
    low_conf = TR.triage(_item(title="ασαφές"), cfg,
                         _llm(lambda s, p: _VERDICT.format(rel="high", conf=0.5)))
    assert low_conf.content_class is ContentClass.C  # below threshold → C


def test_threshold_comes_from_config(cfg):
    cfg.triage.high_confidence = 0.95
    # confidence 0.9 no longer clears the raised bar → Class C
    out = TR.triage(_item(title="ασαφές"), cfg,
                    _llm(lambda s, p: _VERDICT.format(rel="high", conf=0.9)))
    assert out.content_class is ContentClass.C


# --------------------------------------------------------------------------- #
# Story 6.3 — class-aware retention
# --------------------------------------------------------------------------- #
def test_class_b_strips_full_text(cfg):
    item = _item(title="Δασικά", text="μεγάλο κείμενο", topics=["forestry"])
    out = TR.triage(item, cfg, _llm(lambda s, p: "{}"))
    assert out.content_class is ContentClass.B
    assert out.full_text is None and out.snippet is None


def test_class_c_keeps_full_text(cfg):
    item = _item(title="ασαφές", text="κείμενο προς κρίση")
    out = TR.triage(item, cfg, _llm(lambda s, p: _VERDICT.format(rel="medium", conf=0.6)))
    assert out.content_class is ContentClass.C
    assert out.full_text == "κείμενο προς κρίση"


def test_class_c_ttl_sweep_flags_overdue(cfg):
    fresh = _item(cls=ContentClass.C, status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW,
                  collected=_NOW)
    stale = _item(cls=ContentClass.C, status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW,
                  collected=_NOW - timedelta(days=10))
    now = _NOW + timedelta(hours=1)
    flagged = R.sweep_overdue([fresh, stale], cfg, now=now)
    assert flagged == [stale]
    assert stale.overdue is True and fresh.overdue is False


def _gateway():
    return NotionGateway(LocalJSONBackend())


def test_promote_to_a_requires_full_text(cfg):
    gw = _gateway()
    no_text = _item(cls=ContentClass.C, status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW)
    no_text.full_text = None
    with pytest.raises(PermanentError):
        R.promote_class_c_to_a(no_text, gw)   # AD-2: refuse empty promotion


def test_promote_to_a_flips_class_when_text_present(cfg):
    gw = _gateway()
    item = _item(text="πλήρες κείμενο", cls=ContentClass.C,
                 status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW)
    out = R.promote_class_c_to_a(item, gw)
    assert out.content_class is ContentClass.A
    assert out.status is ItemStatus.CLASS_A_AWAITING_INTERPRETATION


def test_downgrade_to_b_purges_full_text(cfg):
    gw = _gateway()
    item = _item(text="κείμενο", cls=ContentClass.C,
                 status=ItemStatus.CLASS_C_AWAITING_HUMAN_REVIEW)
    out = R.downgrade_class_c_to_b(item, gw)
    assert out.content_class is ContentClass.B
    assert out.status is ItemStatus.CLASS_B_INDEXED
    assert out.full_text is None and out.snippet is None
