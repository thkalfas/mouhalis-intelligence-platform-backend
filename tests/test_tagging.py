"""Epic 5 — topic tagging (Stories 5.1 rule-based + EuroVoc, 5.2 LLM fallback)."""
from __future__ import annotations

from datetime import date

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.llm_client import FakeLLMBackend, MeteredLLMClient
from legal_intel.core.models import Item
from legal_intel.pipeline import tag as T
from legal_intel.platform.cost_ledger import CostLedger


@pytest.fixture
def cfg():
    reload_config()
    return load_config()


def _item(title="", text="", hints=None) -> Item:
    return Item(source_id="x", source_name="EUR-Lex", title=title, type="Regulation",
                authority="EU", date_published=date(2026, 7, 8), url="https://x",
                full_text=text or None, descriptor_hints=hints or [])


# --------------------------------------------------------------------------- #
# Story 5.1 — keyword & EuroVoc mapping, constrained to the Ontology
# --------------------------------------------------------------------------- #
def test_keyword_tagging(cfg):
    item = T.tag(_item(title="Οδηγίες ιχνηλασιμότητας καπνικών"), cfg)
    assert "tobacco_traceability" in item.topics


def test_eurovoc_descriptor_maps_to_topic(cfg):
    # No keyword in the text, but a EuroVoc descriptor hint → mapped via Ontology.
    item = T.tag(_item(title="Some EU act", hints=["manufactured tobacco"]), cfg)
    assert "tobacco_traceability" in item.topics


def test_topic_id_hint_honored_when_valid(cfg):
    item = T.tag(_item(title="x", hints=["food_labeling"]), cfg)
    assert "food_labeling" in item.topics


def test_unknown_descriptor_never_creates_topic(cfg):
    item = T.tag(_item(title="Απόφαση για ναυτιλιακά", hints=["maritime", "bogus"]), cfg)
    assert item.topics == []          # neither is an Ontology topic/descriptor


def test_coverage_helper(cfg):
    tagged = _item(title="ιχνηλασιμότητα")
    T.tag(tagged, cfg)
    untagged = _item(title="τίποτα σχετικό")
    T.tag(untagged, cfg)
    assert T.tagging_coverage([tagged, untagged]) == 0.5


# --------------------------------------------------------------------------- #
# Story 5.2 — LLM edge-case tagger (metered, ontology-validated)
# --------------------------------------------------------------------------- #
def _llm(responder):
    return MeteredLLMClient(backend=FakeLLMBackend(responder=responder), sink=CostLedger())


def test_llm_fallback_runs_only_when_rules_find_nothing(cfg):
    calls = []

    def responder(stage, prompt):
        calls.append(stage)
        return '{"topics": ["food_labeling"]}'

    llm = _llm(responder)
    # Rules already tag this (keyword) → LLM must NOT run.
    T.tag(_item(title="ιχνηλασιμότητα καπνικών"), cfg, llm)
    assert calls == []

    # No rule hit → LLM runs and its (valid) proposal is used.
    item = T.tag(_item(title="κάτι ασαφές"), cfg, llm)
    assert calls == ["topic_tag"]
    assert item.topics == ["food_labeling"]


def test_llm_proposals_validated_against_ontology(cfg):
    def responder(stage, prompt):
        return '{"topics": ["food_labeling", "not_a_real_topic"]}'

    item = T.tag(_item(title="ασαφές"), cfg, _llm(responder))
    assert item.topics == ["food_labeling"]   # unknown dropped (AD-7)


def test_llm_fallback_writes_cost_ledger_row(cfg):
    ledger = CostLedger()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: '{"topics": []}'),
                           sink=ledger)
    T.tag(_item(title="ασαφές"), cfg, llm)
    assert any(r.stage == "topic_tag" for r in ledger.rows)


def test_llm_fallback_disabled_by_config(cfg):
    cfg.tagging.llm_fallback = False
    calls = []
    llm = _llm(lambda s, p: calls.append(s) or '{"topics": []}')
    item = T.tag(_item(title="ασαφές"), cfg, llm)
    assert calls == []
    assert item.topics == []
