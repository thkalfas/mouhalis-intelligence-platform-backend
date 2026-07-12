"""Interpretation filter (Story 7.1/7.2/7.3, FR-10/11/12, AD-7/8/9).

Produces a structured, schema-validated draft Interpretation for a Class A Item.
The 7 conceptual steps (legal-type → scope → delta → retrieval → client-impact →
actions → confidence) are, in production, distinct metered LLM calls; Phase 0
issues one metered call whose (fake) output is validated against the schema — a
validation failure fails the Item (never a partial silent record, AD-9).
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from ..core.config import AppConfig
from ..core.errors import PermanentError
from ..core.llm_client import MeteredLLMClient
from ..core.models import Interpretation, Item

_INTERPRET_SYSTEM = (
    "You produce a first-pass structured legal interpretation (not legal advice) "
    "for a Greek wholesale tobacco/food business. Output JSON matching the "
    "Interpretation schema."
)


def _select_model(item: Item, cfg: AppConfig) -> str:
    triggers = cfg.interpretation.escalation_triggers or {}
    topic_triggers = set(triggers.get("topic_in", []))
    if topic_triggers & set(item.topics):
        return cfg.interpretation.escalation_model
    if item.interpretation and item.interpretation.requires_specialist_review:
        return cfg.interpretation.escalation_model
    return cfg.interpretation.default_model


def interpret(item: Item, cfg: AppConfig, llm: MeteredLLMClient) -> Item:
    model = _select_model(item, cfg)
    prompt = json.dumps({
        "title": item.title,
        "type": item.type,
        "authority": item.authority,
        "topics": item.topics,
        "full_text": (item.full_text or "")[:4000],
        "external_commentary": item.external_commentary,
    }, ensure_ascii=False)

    result = llm.complete(stage="interpretation", model=model,
                          system=_INTERPRET_SYSTEM, prompt=prompt,
                          item_id=item.page_id)
    try:
        payload = json.loads(result.text)
        interp = Interpretation(**payload)  # AD-9: validate before persist
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise PermanentError(
            f"Interpretation failed schema validation for {item.dedup_key()}: {exc}"
        ) from exc

    item.interpretation = interp
    item.interpretation_confidence = payload.get("_self_confidence", 0.7)
    return item
