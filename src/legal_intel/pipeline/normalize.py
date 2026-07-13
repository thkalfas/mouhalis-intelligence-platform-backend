"""Normalization filter (Story 1.1, FR-4).

Maps a SourceRecord to a unified Item and is the single place raw bodies become
plain text: adapters download PDF/HTML into ``raw_body`` (they are the only code
that talks to the outside world) and normalization extracts it here, so every
downstream stage sees one clean schema regardless of source. Computes the SHA-256
hash (AD-4 key component), a snippet, detects language (el/en/other), and applies
the data-quality gate.
"""
from __future__ import annotations

from ..core.errors import PermanentError
from ..core.models import Item, SourceRecord, text_hash
from .extract import detect_language, extract_text

SNIPPET_CHARS = 500


def _resolve_text(record: SourceRecord) -> tuple[str, bool]:
    """Return (full_text, needs_ocr). Prefer already-plain text; otherwise
    extract from the raw body the adapter downloaded."""
    if record.full_text:
        return record.full_text, False
    if record.raw_body is not None:
        result = extract_text(record.raw_body, record.content_type)
        return result.text, result.needs_ocr
    return "", False


def normalize(record: SourceRecord) -> Item:
    """Return a normalized Item. Raises PermanentError if the data-quality gate
    fails (empty title/date/url) — caller alerts+skips (AD-12), never persists."""
    if not record.title or not record.url or record.date_published is None:
        raise PermanentError(
            f"Data-quality gate: missing title/date/url for {record.dedup_key()}"
        )

    full_text, needs_ocr = _resolve_text(record)
    text_for_lang = full_text or record.title

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
        language=detect_language(text_for_lang, record.language),
        snippet=(full_text[:SNIPPET_CHARS] or None) if full_text else None,
        hash=text_hash(full_text or record.title),
        needs_ocr=needs_ocr,
        collected_at=record.collected_at,
        primary_source=record.source_name,  # this source is the initial content source
    )
    # Preserve any editorial the source carried, for the interpretation stage.
    commentary = record.raw_metadata.get("external_commentary")
    if commentary:
        item.external_commentary = commentary
    # A superseding version (e.g. an EUR-Lex corrigendum) carries the base
    # identifier of the work it replaces; dedup resolves it to an Item (AD-15).
    supersedes_ref = record.raw_metadata.get("supersedes_ref")
    if supersedes_ref:
        item.supersedes_ref = str(supersedes_ref)
    return item
