"""Config-as-data loader (Story 0.3, AD-8).

Business rules live in config/*.yaml — topics, relevance rules, KAD codes, model
IDs, cadences, authority_rank. Code never hard-codes them. Fail fast on a
missing/malformed file.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


def _project_root() -> Path:
    # src/legal_intel/core/config.py -> project root is three parents up from src
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    return Path(os.environ.get("LEGAL_INTEL_CONFIG", _project_root() / "config"))


def _load_yaml(name: str) -> dict[str, Any]:
    path = config_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"Required config file missing: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # fail fast, don't limp on bad rules
        raise ValueError(f"Malformed YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Config {path} must be a mapping at top level")
    return data


def _load_yaml_optional(name: str) -> dict[str, Any]:
    """Like ``_load_yaml`` but returns ``{}`` if the file is absent (used for
    config that has safe defaults). A malformed present file still fails fast."""
    if not (config_dir() / name).exists():
        return {}
    return _load_yaml(name)


def _load_text_optional(name: str) -> str:
    """Read a plain-text config file (e.g. the Client Context Document); empty
    string if absent."""
    path = config_dir() / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --------------------------------------------------------------------------- #
# Typed config objects
# --------------------------------------------------------------------------- #
class SourceConfig(BaseModel):
    name: str
    tier: int
    endpoint: str = ""
    cadence: str  # e.g. "30m", "6h", "daily@08:00"
    authority_rank: int  # lower = more authoritative (AD-8, L1 fix)
    enabled: bool = True
    adapter: str = ""  # dotted path or key; "fake" for Phase 0
    #: Adapter-specific parameters kept as data (AD-8): lookback windows, EuroVoc
    #: descriptors, org UIDs, RSS urls, api-key env var, resource types, etc.
    #: Adapters read these; code never hard-codes them.
    options: dict[str, Any] = Field(default_factory=dict)


class Topic(BaseModel):
    topic_id: str
    name_gr: str = ""
    name_en: str = ""
    domain: str = ""
    keywords_gr: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    #: EuroVoc descriptors (EUR-Lex pre-filter/mapping) and CELEX types that map
    #: to this Topic (spec §4). Used by the tagger's descriptor path.
    eurovoc_descriptors: list[str] = Field(default_factory=list)
    celex_types: list[str] = Field(default_factory=list)
    priority: str = "medium"


class TaggingConfig(BaseModel):
    #: Run the LLM edge-case tagger when rule-based tagging finds no Topic.
    llm_fallback: bool = True
    #: Optional model override for tagging (else the interpretation default_model).
    model: Optional[str] = None


class TriageConfig(BaseModel):
    #: Confidence above which a high/low LLM verdict is auto-filed to A/B;
    #: everything else routes to Class C (spec §7.2).
    high_confidence: float = 0.85
    #: Class C staging full-text TTL (calendar days) before `overdue` (spec §7.6).
    class_c_ttl_days: int = 7
    #: Class C relevance-review SLA (business days), for metrics/alerts.
    class_c_sla_business_days: int = 2


class RelevanceRule(BaseModel):
    rule_id: str
    action: str  # "classify_A" | "classify_B"
    when: dict[str, Any] = Field(default_factory=dict)


class InterpretationConfig(BaseModel):
    default_model: str
    escalation_model: str
    escalation_triggers: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.2
    max_tokens: int = 4000


class InterpretationExample(BaseModel):
    """A curated gold-standard interpretation used as a few-shot exemplar
    (spec §8.4). Keyed by Topic; the tagger/interpreter pulls matching ones."""

    topic: str
    title: str = ""
    summary: str = ""
    notes: str = ""


class DedupWeights(BaseModel):
    exact_source_id: float = 1.0
    text_hash: float = 0.95
    title_similarity: float = 0.6
    authority_date: float = 0.5
    topic_entity_overlap: float = 0.3


class DedupThresholds(BaseModel):
    title_similarity_min: float = 0.85
    topic_overlap_min: float = 0.70
    auto_merge: float = 0.95
    confirm_low: float = 0.70


class DedupConfig(BaseModel):
    weights: DedupWeights = Field(default_factory=DedupWeights)
    thresholds: DedupThresholds = Field(default_factory=DedupThresholds)
    authority_aliases: dict[str, str] = Field(default_factory=dict)


class AppConfig(BaseModel):
    sources: list[SourceConfig]
    ontology: list[Topic]
    relevance_rules: list[RelevanceRule]
    interpretation: InterpretationConfig
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    tagging: TaggingConfig = Field(default_factory=TaggingConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    interpretation_examples: list[InterpretationExample] = Field(default_factory=list)
    #: Client Context Document (spec §8.7) — cold-start background for the
    #: interpreter's system prompt. Optional; empty until the client supplies it.
    client_context: str = ""
    #: Lookback window: Items whose publication date is older than this many days
    #: are skipped before triage/interpretation (bounds a first-run backfill and
    #: saves LLM cost). 0 disables the filter; undated Items always pass.
    max_age_days: int = 180
    kad_codes: list[str] = Field(default_factory=list)

    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def authority_rank(self, source_name: str) -> int:
        for s in self.sources:
            if s.name == source_name:
                return s.authority_rank
        return 999  # unknown source ranks last


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    sources_raw = _load_yaml("sources.yaml")
    ontology_raw = _load_yaml("ontology.yaml")
    rules_raw = _load_yaml("relevance_rules.yaml")
    interp_raw = _load_yaml("interpretation_config.yaml")
    dedup_raw = _load_yaml("dedup.yaml")
    tagging_raw = _load_yaml_optional("tagging.yaml")
    examples_raw = _load_yaml_optional("interpretation_examples.yaml")
    client_context = _load_text_optional("client_context.md")

    return AppConfig(
        sources=[SourceConfig(**s) for s in sources_raw.get("sources", [])],
        ontology=[Topic(**t) for t in ontology_raw.get("topics", [])],
        relevance_rules=[RelevanceRule(**r) for r in rules_raw.get("rules", [])],
        interpretation=InterpretationConfig(**interp_raw["interpretation"]),
        dedup=DedupConfig(**dedup_raw),
        tagging=TaggingConfig(**tagging_raw),
        triage=TriageConfig(**rules_raw.get("triage", {})),
        interpretation_examples=[InterpretationExample(**e)
                                 for e in examples_raw.get("examples", [])],
        client_context=client_context,
        max_age_days=int(sources_raw.get("max_age_days", 180)),
        kad_codes=[str(k) for k in rules_raw.get("kad_codes", [])],
    )


def reload_config() -> AppConfig:
    load_config.cache_clear()
    return load_config()
