"""Topic tagging filter (Story 5.1, FR-6, AD-8).

Rule-based first: match Ontology keywords (GR/EN) against title + full text. Topics
are drawn only from the validated Ontology — an unknown token never creates a Topic.
The LLM edge-case tagger (Story 5.2) is a later plug-in via the MeteredLLMClient.
"""
from __future__ import annotations

from ..core.config import AppConfig
from ..core.models import Item


def tag(item: Item, cfg: AppConfig) -> Item:
    haystack = f"{item.title}\n{item.full_text or ''}".lower()
    found: list[str] = []
    for topic in cfg.ontology:
        keywords = [k.lower() for k in (topic.keywords_gr + topic.keywords_en)]
        if any(kw in haystack for kw in keywords):
            found.append(topic.topic_id)
    # Also honor an explicit topics hint from the source (e.g. mapped descriptors),
    # but only if it names a real Ontology topic.
    valid_ids = {t.topic_id for t in cfg.ontology}
    for hint in item_topics_hint(item):
        if hint in valid_ids and hint not in found:
            found.append(hint)
    item.topics = found
    return item


def item_topics_hint(item: Item) -> list[str]:
    # Placeholder hook: real descriptor→topic mapping arrives with EUR-Lex EuroVoc
    # pre-filtering in Epic 1/5. Kept minimal for Phase 0.
    return []
