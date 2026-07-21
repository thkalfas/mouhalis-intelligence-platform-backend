"""Robust LLM JSON extraction — real models wrap JSON in fences/prose."""
from __future__ import annotations

import json

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.llm_client import (FakeLLMBackend, MeteredLLMClient,
                                         extract_json)
from legal_intel.core.models import ContentClass, Item, ItemStatus
from legal_intel.platform.cost_ledger import CostLedger
from legal_intel.pipeline import triage as TR


def test_extract_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_surrounding_prose():
    text = 'Here is the analysis:\n{"relevance": "high", "confidence": 0.9}\nHope that helps!'
    assert extract_json(text)["relevance"] == "high"


def test_extract_json_raises_when_absent():
    with pytest.raises(json.JSONDecodeError):
        extract_json("no json here at all")


def test_triage_survives_malformed_classifier_output():
    # A classifier that returns prose (not JSON) must NOT crash the run — the
    # item routes to Class C for human review (AD-12).
    reload_config()
    cfg = load_config()
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: "sorry, no JSON"),
                           sink=CostLedger())
    item = Item(source_id="x", source_name="EUR-Lex", title="ασαφές", type="doc",
                authority="a", full_text="κάτι", status=ItemStatus.AWAITING_TRIAGE)
    out = TR.triage(item, cfg, llm)
    assert out.content_class is ContentClass.C


def test_triage_parses_fenced_classifier_output():
    reload_config()
    cfg = load_config()
    fenced = '```json\n{"relevance": "high", "confidence": 0.95, "reasoning": "r"}\n```'
    llm = MeteredLLMClient(backend=FakeLLMBackend(responder=lambda s, p: fenced),
                           sink=CostLedger())
    item = Item(source_id="x", source_name="EUR-Lex", title="σχετικό", type="doc",
                authority="a", full_text="κάτι", status=ItemStatus.AWAITING_TRIAGE)
    out = TR.triage(item, cfg, llm)
    assert out.content_class is ContentClass.A
