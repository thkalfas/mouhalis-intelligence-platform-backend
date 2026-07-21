"""Interpretation filter (Story 7.1/7.2/7.3, FR-10/11/12, AD-7/8/9).

Produces a structured, schema-validated draft Interpretation for a Class A Item —
the blank-page killer. The 7 conceptual steps (legal-type → scope → delta →
retrieval → client-impact → actions → confidence) are realised as a deterministic
retrieval/augmentation step feeding a single structured generation whose output
covers the reasoning sections; a validation failure fails the Item (never a
partial silent record, AD-9). Production may split the generation into per-step
metered calls without changing this contract.

Retrieval augmentation (Story 7.2): 3–5 related Items (same Topic + authority,
≤3 years) plus gold-standard few-shot Examples and the Client Context Document
ground the reading; cold start proceeds on the Client Context Document alone.

Model escalation (Story 7.3): high-stakes topics or a specialist-flagged Item use
the escalation model; every call is metered and all model ids come from config.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import ValidationError

from ..core.config import AppConfig
from ..core.errors import PermanentError
from ..core.llm_client import MeteredLLMClient, extract_json
from ..core.models import Interpretation, Item
from ..platform.logging import get_logger

_INTERPRET_SYSTEM = (
    "You produce a first-pass structured legal interpretation (NOT legal advice) "
    "for a Greek wholesale tobacco/food + franchised retail food-service business "
    "(KAD 46.35, 46.37, 46.38, 56.10, 56.30). Work through: legal type, scope, "
    "what changed (before/after/delta), client impact, concrete actions with "
    "owners/deadlines, and a confidence self-assessment. Output ONLY the JSON "
    "object matching the Interpretation schema — no markdown fences, no prose. "
    "Keys: summary, what_changed_before, what_changed_after, what_changed_delta, "
    "business_lines_affected[], support_functions_affected[], operational_impact, "
    "compliance_new_obligations[], compliance_lifted_obligations[], "
    "actions_required[{action, owner_role, deadline, priority, estimated_effort}], "
    "entry_into_force, transition_end, cited_articles[], confidence_notes, "
    "requires_specialist_review, specialist_domain. All prose in Greek, but "
    "'priority' and 'estimated_effort' MUST be exactly one of: low, medium, high."
)

# The 7 conceptual steps, logged for traceability (spec §8.3).
_STEPS = ("legal_type", "scope", "delta", "retrieval",
          "client_impact", "actions", "confidence")


# --------------------------------------------------------------------------- #
# Step 4 — retrieval augmentation (deterministic)
# --------------------------------------------------------------------------- #
def retrieve_related(item: Item, known: list[Item],
                     now: Optional[datetime] = None, *, years: int = 3,
                     limit: int = 5) -> list[Item]:
    """Related prior Items: overlapping Topic AND same authority, published within
    the last ``years``. Newest first, capped at ``limit`` (spec §8.3 step 4)."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=365 * years)).date()
    item_topics = set(item.topics)
    out: list[Item] = []
    for other in known:
        if other.page_id and other.page_id == item.page_id:
            continue
        if other is item:
            continue
        if not (item_topics & set(other.topics)):
            continue
        if other.authority != item.authority:
            continue
        if other.date_published and other.date_published < cutoff:
            continue
        out.append(other)
    out.sort(key=lambda i: (i.date_published or cutoff), reverse=True)
    return out[:limit]


def few_shot_examples(item: Item, cfg: AppConfig, limit: int = 3):
    topics = set(item.topics)
    return [e for e in cfg.interpretation_examples if e.topic in topics][:limit]


# --------------------------------------------------------------------------- #
# Step 7.3 — model selection
# --------------------------------------------------------------------------- #
def _select_model(item: Item, cfg: AppConfig) -> str:
    triggers = cfg.interpretation.escalation_triggers or {}
    if set(triggers.get("topic_in", [])) & set(item.topics):
        return cfg.interpretation.escalation_model
    # self_flag: escalate when triage flagged the Item for specialist review. The
    # flag is known pre-interpretation from triage (item.specialist_needed).
    if triggers.get("self_flag") and item.specialist_needed:
        return cfg.interpretation.escalation_model
    return cfg.interpretation.default_model


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #
def _build_prompt(item: Item, related: list[Item], examples, client_context: str) -> str:
    return json.dumps({
        "client_context": client_context or "(none supplied — use the KAD profile)",
        "item": {
            "title": item.title,
            "type": item.type,
            "authority": item.authority,
            "topics": item.topics,
            "full_text": (item.full_text or "")[:4000],
            "external_commentary": item.external_commentary,
        },
        "related_precedents": [
            {"source_id": r.source_id, "title": r.title,
             "date": r.date_published.isoformat() if r.date_published else None}
            for r in related
        ],
        "few_shot_examples": [
            {"topic": e.topic, "title": e.title, "summary": e.summary} for e in examples
        ],
    }, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def interpret(item: Item, cfg: AppConfig, llm: MeteredLLMClient,
              known: Optional[list[Item]] = None,
              now: Optional[datetime] = None) -> Item:
    log = get_logger()
    now = now or datetime.now(timezone.utc)
    related = retrieve_related(item, known or [], now)
    examples = few_shot_examples(item, cfg)
    log.log(source="interpret", event="interpretation_retrieval", status="ok",
            item_id=item.page_id, related=len(related), few_shot=len(examples))

    model = _select_model(item, cfg)
    prompt = _build_prompt(item, related, examples, cfg.client_context)
    for step in _STEPS:  # traceability: which conceptual step (spec §8.3)
        log.log(source="interpret", event="step", status=step, item_id=item.page_id)

    result = llm.complete(stage="interpretation", model=model,
                          system=_INTERPRET_SYSTEM, prompt=prompt,
                          item_id=item.page_id)
    try:
        payload = extract_json(result.text)
        interp = Interpretation(**payload)  # AD-9: validate before persist
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise PermanentError(
            f"Interpretation failed schema validation for {item.dedup_key()}: {exc}"
        ) from exc

    item.interpretation = interp
    item.interpretation_confidence = payload.get("_self_confidence", 0.7)
    item.draft_created_at = now  # metric anchor for time-to-approval (spec §9.5)
    return item
