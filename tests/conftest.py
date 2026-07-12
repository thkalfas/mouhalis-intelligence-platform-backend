"""Shared fixtures. Each test gets an isolated in-memory Notion gateway and a
metered LLM client wired to the Phase-0 fake responder + a fresh cost ledger.
"""
from __future__ import annotations

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.llm_client import FakeLLMBackend, MeteredLLMClient
from legal_intel.core.notion_gateway import LocalJSONBackend, NotionGateway
from legal_intel.pipeline.runner import PipelineRunner, phase0_responder
from legal_intel.platform.cost_ledger import CostLedger


@pytest.fixture
def cfg():
    reload_config()  # ensure a clean cache against the repo config/
    return load_config()


@pytest.fixture
def gateway():
    return NotionGateway(LocalJSONBackend())


@pytest.fixture
def ledger():
    return CostLedger()


@pytest.fixture
def runner(cfg, gateway, ledger):
    llm = MeteredLLMClient(
        backend=FakeLLMBackend(responder=phase0_responder), sink=ledger
    )
    return PipelineRunner(cfg=cfg, gateway=gateway, llm=llm, ledger=ledger)
