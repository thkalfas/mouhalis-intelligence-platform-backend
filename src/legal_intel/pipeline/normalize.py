"""Normalization filter (Story 1.1, FR-4).

Maps a SourceRecord to a unified Item: text extraction is assumed already-plain
here (Tier-1 adapters extract; the PDF/HTML extractors land in Epic 1/3), computes
the SHA-256 hash (AD-4 key component), a snippet, and applies the data-quality gate.
"""
from __future__ import annotations

from typing import Optional

from ..core.errors import PermanentError
from ..core.models import Item, SourceRecord, text_hash

SNIPPET_CHARS = 500


def _detect_language(text: str, hint: Optional[str]) -> str:
    if hint:
        return hint
    # Cheap heuristic sufficient for Phase 0; real detection in Epic 1.
    greek = sum(1 for ch in text if "Ͱ" <= ch <= "Ͽ")
    return "el" if greek > len(text) * 0.2 else "en"


def normalize(record: SourceRecord) -> Item:
    """Return a normalized Item. Raises PermanentError if the data-quality gate
    fails (empty title/date/url) — caller alerts+skips (AD-12), never persists."""
    if not record.title or not record.url or record.date_published is None:
        raise PermanentError(
            f"Data-quality gate: missing title/date/url for {record.dedup_key()}"
        )

    full_text = record.full_text or ""
    item = Item(
        source_id=record.source_id,
        source_name=record.source_name,
        title=record.title.strip(),
        type=record.type,
        authority=record.authority,
        date_published=record.date_published,
        date_effective=record.date_effective,
        url=record.url,
        full_text=full_text or None,
        language=_detect_language(full_text or record.title, record.language),
        snippet=(full_text[:SNIPPET_CHARS] or None) if full_text else None,
        hash=text_hash(full_text or record.title),
        collected_at=record.collected_at,
    )
    # Preserve any editorial the source carried, for the interpretation stage.
    commentary = record.raw_metadata.get("external_commentary")
    if commentary:
        item.external_commentary = commentary
    return item
