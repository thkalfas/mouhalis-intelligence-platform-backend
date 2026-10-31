"""Epic 1 — adapter registry wires config-selected sources."""
from __future__ import annotations

import pytest

from legal_intel.adapters.diavgeia import DiavgeiaAdapter
from legal_intel.adapters.eurlex import EurLexAdapter
from legal_intel.adapters.fake import FakeSourceAdapter
from legal_intel.adapters.registry import build_adapter, build_enabled_adapters
from legal_intel.core.config import SourceConfig, load_config


def test_build_fake_needs_no_config():
    cfg = SourceConfig(name="FakeSource", tier=1, cadence="30m",
                       authority_rank=1, adapter="fake")
    assert isinstance(build_adapter(cfg), FakeSourceAdapter)


def test_build_real_adapters_by_key():
    eur = SourceConfig(name="EUR-Lex", tier=1, endpoint="http://x", cadence="30m",
                       authority_rank=1, adapter="eurlex")
    dia = SourceConfig(name="Διαύγεια", tier=1, endpoint="http://y", cadence="6h",
                       authority_rank=1, adapter="diavgeia")
    assert isinstance(build_adapter(eur), EurLexAdapter)
    assert isinstance(build_adapter(dia), DiavgeiaAdapter)


def test_unknown_adapter_raises():
    cfg = SourceConfig(name="X", tier=1, cadence="30m", authority_rank=1, adapter="nope")
    with pytest.raises(ValueError):
        build_adapter(cfg)


def test_missing_adapter_key_raises():
    cfg = SourceConfig(name="X", tier=1, cadence="30m", authority_rank=1, adapter="")
    with pytest.raises(ValueError):
        build_adapter(cfg)


def test_only_validated_sources_enabled():
    app_cfg = load_config()
    names = [a.name for a in build_enabled_adapters(app_cfg)]
    assert names == ["EUR-Lex", "Διαύγεια", "Βουλή", "EDPB", "EFSA", "GDPRhub",
                     "ΦΕΚ", "ΕπΑντ", "ΕΦΕΤ", "RASFF", "dpa.gr"]


def test_real_config_carries_adapter_options():
    app_cfg = load_config()
    eurlex = next(s for s in app_cfg.sources if s.name == "EUR-Lex")
    assert eurlex.adapter == "eurlex"
    assert "tobacco industry" in eurlex.options["eurovoc_descriptors"]
    assert eurlex.options["lookback_days"] == 30
