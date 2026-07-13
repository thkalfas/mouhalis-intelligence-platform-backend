"""Epic 7 — interpretation engine (Stories 7.1 validation, 7.2 retrieval, 7.3 escalation)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from legal_intel.core.config import (AppConfig, InterpretationExample,
                                     load_config, reload_config)
from legal_intel.core.errors import PermanentError
from legal_intel.core.llm_client import FakeLLMBackend, MeteredLLMClient
from legal_intel.core.models import ContentClass, Item
from legal_intel.pipeline import interpret as I
from legal_intel.platform.cost_ledger import CostLedger

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)

_VALID_INTERP = {
    "summary": "σύνοψη", "what_changed_before": "πριν", "what_changed_after": "μετά",
    "what_changed_delta": "διαφορά", "requires_specialist_review": False,
}


@pytest.fixture
def cfg():
    reload_config()
    return load_config()


def _item(*, title="Κανονισμός", topics=None, authority="EU",
          text="κείμενο", cls=ContentClass.A, dp=date(2026, 7, 8),
          specialist=None, page_id="p1") -> Item:
    return Item(source_id="s1", source_name="EUR-Lex", title=title, type="Regulation",
                authority=authority, date_published=dp, url="https://x",
                full_text=text, topics=topics or [], content_class=cls,
                specialist_needed=specialist, page_id=page_id, collected_at=_NOW)


def _llm(responder):
    return MeteredLLMClient(backend=FakeLLMBackend(responder=responder), sink=CostLedger())


# --------------------------------------------------------------------------- #
# Story 7.1 — schema validation
# --------------------------------------------------------------------------- #
def test_valid_interpretation_persists_with_disclaimer(cfg):
    item = _item()
    out = I.interpret(item, cfg, _llm(lambda s, p: json.dumps(_VALID_INTERP)))
    assert out.interpretation is not None
    assert out.interpretation.summary == "σύνοψη"
    assert "νομική συμβουλή" in out.interpretation.disclaimer  # not-legal-advice


def test_invalid_interpretation_fails_item_no_partial(cfg):
    # Missing required fields → validation error → PermanentError, nothing set.
    item = _item()
    with pytest.raises(PermanentError):
        I.interpret(item, cfg, _llm(lambda s, p: json.dumps({"summary": "only"})))
    assert item.interpretation is None


def test_non_json_output_fails_item(cfg):
    item = _item()
    with pytest.raises(PermanentError):
        I.interpret(item, cfg, _llm(lambda s, p: "not json"))


# --------------------------------------------------------------------------- #
# Story 7.2 — retrieval augmentation & few-shot
# --------------------------------------------------------------------------- #
def test_retrieve_related_matches_topic_and_authority(cfg):
    item = _item(topics=["food_labeling"], authority="EFSA", page_id="target")
    same = _item(title="σχετικό", topics=["food_labeling"], authority="EFSA",
                 dp=date(2025, 1, 1), page_id="rel1")
    other_authority = _item(topics=["food_labeling"], authority="EU", page_id="rel2")
    other_topic = _item(topics=["tobacco_excise"], authority="EFSA", page_id="rel3")
    too_old = _item(topics=["food_labeling"], authority="EFSA",
                    dp=date(2010, 1, 1), page_id="rel4")

    related = I.retrieve_related(item, [item, same, other_authority, other_topic, too_old],
                                 now=_NOW)
    ids = [r.page_id for r in related]
    assert ids == ["rel1"]  # only same topic+authority within 3 years, self excluded


def test_related_capped_at_limit(cfg):
    item = _item(topics=["food_labeling"], authority="EFSA", page_id="t")
    pool = [item] + [_item(topics=["food_labeling"], authority="EFSA",
                           dp=date(2025, 1, 1 + i), page_id=f"r{i}") for i in range(9)]
    related = I.retrieve_related(item, pool, now=_NOW, limit=5)
    assert len(related) == 5


def test_few_shot_examples_filtered_by_topic():
    cfg = AppConfig.model_construct(
        interpretation_examples=[
            InterpretationExample(topic="food_labeling", title="ex1", summary="s1"),
            InterpretationExample(topic="tobacco_excise", title="ex2", summary="s2"),
        ])
    item = _item(topics=["food_labeling"])
    examples = I.few_shot_examples(item, cfg)
    assert [e.title for e in examples] == ["ex1"]


def test_cold_start_proceeds_without_related(cfg):
    # No related items, no examples → still produces a valid interpretation.
    item = _item(topics=["gdpr_direct_marketing"])
    out = I.interpret(item, cfg, _llm(lambda s, p: json.dumps(_VALID_INTERP)), known=[item])
    assert out.interpretation is not None


# --------------------------------------------------------------------------- #
# Story 7.3 — model selection & escalation
# --------------------------------------------------------------------------- #
def test_default_model_used_when_no_trigger(cfg):
    seen = {}
    def responder(stage, prompt):
        return json.dumps(_VALID_INTERP)
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=responder), sink=(led := CostLedger()))
    I.interpret(_item(topics=["food_labeling"]), cfg, llm)
    assert led.rows[-1].model == cfg.interpretation.default_model


def test_escalation_on_high_stakes_topic(cfg):
    led = CostLedger()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: json.dumps(_VALID_INTERP)),
                           sink=led)
    I.interpret(_item(topics=["csrd_scope"]), cfg, llm)
    assert led.rows[-1].model == cfg.interpretation.escalation_model


def test_escalation_on_specialist_flag(cfg):
    led = CostLedger()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: json.dumps(_VALID_INTERP)),
                           sink=led)
    I.interpret(_item(topics=["food_labeling"], specialist=True), cfg, llm)
    assert led.rows[-1].model == cfg.interpretation.escalation_model


def test_interpretation_call_is_metered(cfg):
    led = CostLedger()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: json.dumps(_VALID_INTERP)),
                           sink=led)
    I.interpret(_item(), cfg, llm)
    assert any(r.stage == "interpretation" for r in led.rows)
