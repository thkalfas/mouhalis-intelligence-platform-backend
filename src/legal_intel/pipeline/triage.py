"""Relevance triage filter (Story 6.1/6.2/6.3, FR-7/8/9, AD-8/13).

Deterministic rules first (cheap, predictable), then the LLM classifier for
undecided items — the classifier is INVOKED BY this stage, which owns the
`Awaiting Triage` status (AD-13). Applies class-aware retention (AD-5).
"""
from __future__ import annotations

import json
from typing import Optional

from ..core.config import AppConfig
from ..core.llm_client import MeteredLLMClient, extract_json
from ..core.models import ClassReasoning, ContentClass, DecidedBy, Item

_CLASSIFIER_SYSTEM = (
    "You are a legal relevance classifier for a wholesale tobacco/food + "
    "franchised retail food-service business (KAD 46.35, 46.37, 46.38, 56.10, "
    "56.30) in Greece + EU. Return JSON with keys: relevance (high|medium|low), "
    "confidence (0..1), reasoning (Greek, 2-3 sentences), sector_touchpoints "
    "(array), action_signal (immediate|monitor|none), specialist_needed (bool). "
    "Prefer 'medium' over guessing when uncertain. Output ONLY the JSON object — "
    "no markdown fences, no prose."
)


def _apply_rules(item: Item, cfg: AppConfig) -> Optional[tuple[ContentClass, str]]:
    """Return (class, rule_id) if a deterministic rule is decisive, else None."""
    text = f"{item.title}\n{item.full_text or ''}".lower()
    for rule in cfg.relevance_rules:
        when = rule.when
        # include: direct KAD mention
        if "text_contains_kad_any" in when:
            kads = when["text_contains_kad_any"] or cfg.kad_codes
            if any(str(k) in text for k in kads):
                return (_class_for(rule.action), rule.rule_id)
        # include: high-priority topic hit
        if "topics_contains_any" in when:
            if set(when["topics_contains_any"]) & set(item.topics):
                return (_class_for(rule.action), rule.rule_id)
        # exclude: all topics in an excluded set
        if "topics_all_in" in when and item.topics:
            if set(item.topics).issubset(set(when["topics_all_in"])):
                return (_class_for(rule.action), rule.rule_id)
    return None


def _class_for(action: str) -> ContentClass:
    return ContentClass.A if action == "classify_A" else ContentClass.B


def _apply_retention(item: Item) -> None:
    """Class-aware retention (AD-5): Class B carries no full text/snippet."""
    if item.content_class is ContentClass.B:
        item.full_text = None
        item.snippet = None


def triage(item: Item, cfg: AppConfig, llm: MeteredLLMClient) -> Item:
    # 1) Deterministic rules
    decided = _apply_rules(item, cfg)
    if decided is not None:
        content_class, rule_id = decided
        item.content_class = content_class
        item.class_reasoning = ClassReasoning(
            decided_by=DecidedBy.RULE,
            detail=f"Rule {rule_id} fired.",
            rule_id=rule_id,
        )
        _apply_retention(item)
        return item

    # 2) LLM classifier (metered) for undecided items
    prompt = json.dumps({
        "title": item.title,
        "type": item.type,
        "authority": item.authority,
        "topics": item.topics,
        "snippet": (item.full_text or "")[:500],
    }, ensure_ascii=False)
    result = llm.complete(stage="relevance_classify",
                          model=cfg.interpretation.default_model,
                          system=_CLASSIFIER_SYSTEM, prompt=prompt,
                          item_id=item.page_id)
    # A malformed classifier response must not crash the run (AD-12): treat it as
    # "undecided" → Class C for a human to relevance-check.
    try:
        verdict = extract_json(result.text)
    except (json.JSONDecodeError, ValueError):
        verdict = {"relevance": "medium", "confidence": 0.0,
                   "reasoning": "Ο ταξινομητής επέστρεψε μη έγκυρη απάντηση — "
                                "παραπομπή σε ανθρώπινο έλεγχο."}
    relevance = verdict.get("relevance", "medium")
    confidence = float(verdict.get("confidence", 0.5))
    item.confidence_score = confidence
    # Capture the classifier's structured signals (Story 6.2) for downstream
    # routing and review SLAs (action_signal drives the WF2 24h fast-track).
    touchpoints = verdict.get("sector_touchpoints") or []
    item.sector_touchpoints = [str(t) for t in touchpoints] if isinstance(touchpoints, list) else []
    item.action_signal = verdict.get("action_signal")
    if "specialist_needed" in verdict:
        item.specialist_needed = bool(verdict["specialist_needed"])

    threshold = cfg.triage.high_confidence
    if relevance == "high" and confidence > threshold:
        item.content_class = ContentClass.A
    elif relevance == "low" and confidence > threshold:
        item.content_class = ContentClass.B
    else:
        item.content_class = ContentClass.C

    item.class_reasoning = ClassReasoning(
        decided_by=DecidedBy.LLM,
        detail=verdict.get("reasoning", "LLM classification."),
    )
    _apply_retention(item)
    return item
