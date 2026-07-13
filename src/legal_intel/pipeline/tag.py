"""Topic tagging filter (Story 5.1/5.2, FR-6, AD-7/8).

Rule-based first (cheap, deterministic): match Ontology keywords (GR/EN) against
title + full text, and map source-provided EuroVoc descriptors/hints to Topics
via the Ontology. Every assigned Topic is drawn ONLY from the validated Ontology
— an unknown keyword or descriptor never creates a Topic.

For Items that rule-based tagging leaves untagged, an LLM edge-case tagger
(Story 5.2) proposes Topics via the MeteredLLMClient; its output is likewise
constrained to the Ontology before persist (AD-7). The LLM path is config-gated
(`tagging.llm_fallback`) and only ever runs on the rule-based misses.
"""
from __future__ import annotations

import json
from typing import Optional

from ..core.config import AppConfig
from ..core.llm_client import MeteredLLMClient
from ..core.models import Item

_TAGGER_SYSTEM = (
    "You tag Greek/EU legal items with compliance topics for a wholesale "
    "tobacco/food + franchised retail food-service business. Choose only from the "
    "provided topic ids; return JSON {\"topics\": [ids]}. Empty if none apply."
)


def _rule_based_topics(item: Item, cfg: AppConfig) -> list[str]:
    haystack = f"{item.title}\n{item.full_text or ''}".lower()
    valid_ids = {t.topic_id for t in cfg.ontology}
    found: list[str] = []

    for topic in cfg.ontology:
        keywords = [k.lower() for k in (topic.keywords_gr + topic.keywords_en)]
        if any(kw in haystack for kw in keywords):
            found.append(topic.topic_id)

    # EuroVoc descriptor / source-hint mapping (Story 5.1). A hint that names a
    # real topic_id is honored directly; otherwise it is matched to a Topic whose
    # eurovoc_descriptors contain it. Unknown hints are ignored (never a Topic).
    hints_lower = {h.lower() for h in item.descriptor_hints}
    if hints_lower:
        for topic in cfg.ontology:
            if topic.topic_id in found:
                continue
            descriptors = {d.lower() for d in topic.eurovoc_descriptors}
            if (topic.topic_id.lower() in hints_lower) or (descriptors & hints_lower):
                found.append(topic.topic_id)
    for hint in item.descriptor_hints:
        if hint in valid_ids and hint not in found:
            found.append(hint)

    # De-dup, preserve order.
    return list(dict.fromkeys(found))


def _llm_tag(item: Item, cfg: AppConfig, llm: MeteredLLMClient) -> list[str]:
    valid_ids = [t.topic_id for t in cfg.ontology]
    prompt = json.dumps({
        "title": item.title,
        "snippet": (item.full_text or "")[:500],
        "allowed_topic_ids": valid_ids,
    }, ensure_ascii=False)
    result = llm.complete(
        stage="topic_tag",
        model=cfg.tagging.model or cfg.interpretation.default_model,
        system=_TAGGER_SYSTEM, prompt=prompt, item_id=item.page_id,
    )
    try:
        proposed = json.loads(result.text).get("topics", [])
    except (ValueError, AttributeError):
        proposed = []
    # Validate against the Ontology before persist (AD-7) — drop anything unknown.
    valid = set(valid_ids)
    return [t for t in proposed if t in valid]


def tag(item: Item, cfg: AppConfig, llm: Optional[MeteredLLMClient] = None) -> Item:
    topics = _rule_based_topics(item, cfg)
    if not topics and llm is not None and cfg.tagging.llm_fallback:
        topics = _llm_tag(item, cfg, llm)
    item.topics = topics
    return item


def tagging_coverage(items: list[Item]) -> float:
    """Share of Items carrying ≥1 Topic (data-quality gate target >0.90, spec §12)."""
    if not items:
        return 1.0
    tagged = sum(1 for it in items if it.topics)
    return tagged / len(items)
