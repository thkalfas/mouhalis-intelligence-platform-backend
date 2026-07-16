"""Item ⇄ Notion property mapping (Story 0.5 provisioning, AD-2/AD-11).

Pure translation between the domain ``Item`` and the Notion "Legal Events"
database schema — no network here, so it is fully unit-tested offline. The real
``NotionApiBackend`` (in notion_gateway) calls ``item_to_properties`` /
``item_to_children`` and hands the result to notion-client.

Two rules matter for correctness:
  - **Never clobber human-owned fields.** The pipeline only ever *adds* to a
    page; a property is emitted only when the Item actually carries a value, so
    a reviewer's edits in Notion (Status they moved, notes they wrote) survive a
    later pipeline re-write. Human-managed people fields (Reviewer, Action Owner)
    are never written by the pipeline at all — they are set in Notion.
  - **Class-aware body (AD-5).** Full text lives in the page *body*, not a
    property, and only for Class A/C; Class B carries none. The caller already
    strips B's text via ``to_payload``.

Property names here are the Notion display names of the provisioned schema; keep
them in sync if the database changes.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from .models import ContentClass, Item

# Notion rich_text hard-caps a single text node at 2000 chars.
_MAX_TEXT = 2000
_MAX_BODY_BLOCKS = 90


# --------------------------------------------------------------------------- #
# Notion property value builders (API v1 shape)
# --------------------------------------------------------------------------- #
def _title(text: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": (text or "")[:_MAX_TEXT]}}]}


def _rich_text(text: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": text[:_MAX_TEXT]}}]}


def _select(name: str) -> dict:
    return {"select": {"name": name}}


def _multi_select(names: list[str]) -> dict:
    return {"multi_select": [{"name": n} for n in names]}


def _date(value) -> dict:
    iso = value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    return {"date": {"start": iso}}


def _number(x: float) -> dict:
    return {"number": x}


def _checkbox(b: bool) -> dict:
    return {"checkbox": bool(b)}


def _url(u: str) -> dict:
    return {"url": u or None}


def _relation(ids: list[str]) -> dict:
    return {"relation": [{"id": i} for i in ids]}


def _looks_like_notion_id(value: str) -> bool:
    hexed = value.replace("-", "")
    return len(hexed) == 32 and all(c in "0123456789abcdefABCDEF" for c in hexed)


# --------------------------------------------------------------------------- #
# Field composition helpers
# --------------------------------------------------------------------------- #
def _additional_sources(item: Item) -> Optional[str]:
    if not item.additional_sources:
        return None
    return "\n".join(f"{s.source} — {s.url}" for s in item.additional_sources)


def _critical_dates(item: Item) -> Optional[str]:
    interp = item.interpretation
    if not interp:
        return None
    parts = []
    if interp.entry_into_force:
        parts.append(f"Έναρξη ισχύος: {interp.entry_into_force}")
    if interp.transition_end:
        parts.append(f"Λήξη μεταβατικής: {interp.transition_end}")
    return " · ".join(parts) or None


def _recommended_actions(item: Item) -> Optional[str]:
    interp = item.interpretation
    if not interp or not interp.actions_required:
        return None
    lines = [f"- {a.action} ({a.owner_role}, {a.deadline}, {a.priority})"
             for a in interp.actions_required]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Item → properties
# --------------------------------------------------------------------------- #
def item_to_properties(item: Item) -> dict[str, Any]:
    """Notion properties payload for a create/update. Only present values are
    emitted (see module docstring — never clobber human edits)."""
    props: dict[str, Any] = {"Title": _title(item.title)}

    def put(name: str, value, builder) -> None:
        if value is None:
            return
        if isinstance(value, (list, str)) and len(value) == 0:
            return
        props[name] = builder(value)

    # Identity / provenance
    put("Status", item.status.value if item.status else None, _select)
    put("Content Class", item.content_class.value if item.content_class else None, _select)
    put("Source", item.source_name, _select)
    put("Source ID", item.source_id, _rich_text)
    put("Authority", item.authority, _rich_text)
    put("Type", item.type, _rich_text)
    put("Date Published", item.date_published, _date)
    put("Date Effective", item.date_effective, _date)
    put("URL", item.url, _url)
    put("Additional Sources", _additional_sources(item), _rich_text)
    put("External Commentary", item.external_commentary, _rich_text)
    put("Jurisdiction", item.jurisdiction, _select)
    put("Language", item.language, _select)

    # Classification
    if item.class_reasoning:
        detail = item.class_reasoning.detail
        if item.class_reasoning.rule_id:
            detail = f"{detail} [rule: {item.class_reasoning.rule_id}]"
        put("Class Reasoning", detail, _rich_text)
        put("Decided By", item.class_reasoning.decided_by.value, _select)
    put("Confidence Score", item.confidence_score, _number)
    put("Topics", item.topics, _multi_select)
    put("Sector Touchpoints", item.sector_touchpoints, _multi_select)
    put("Action Signal", item.action_signal, _select)
    if item.specialist_needed is not None:
        props["Specialist Needed"] = _checkbox(item.specialist_needed)
    put("Dedup Score", item.dedup_score, _number)

    # Interpretation
    if item.interpretation:
        interp = item.interpretation
        put("Interpretation Summary", interp.summary, _rich_text)
        put("What Changed - Before", interp.what_changed_before, _rich_text)
        put("What Changed - After", interp.what_changed_after, _rich_text)
        put("What Changed - Delta", interp.what_changed_delta, _rich_text)
        put("Critical Dates", _critical_dates(item), _rich_text)
        put("Recommended Actions", _recommended_actions(item), _rich_text)
        put("Disclaimer", interp.disclaimer, _rich_text)
    put("Interpretation Confidence", item.interpretation_confidence, _number)

    # Review workflow (only the pipeline-owned fields; people fields are
    # human-managed in Notion and never written here).
    put("Client Action Status", item.client_action_status, _select)
    put("Action Deadline", item.action_deadline, _date)
    put("Review Notes", item.review_notes, _rich_text)
    props["Overdue"] = _checkbox(item.overdue)
    props["Reclassify Requested"] = _checkbox(item.reclassify_requested)
    props["Reclassified From B"] = _checkbox(item.reclassified_from_b)

    # Relations (precedent chain) — only if the ids are Notion page ids.
    supersedes = [s for s in item.supersedes if _looks_like_notion_id(s)]
    if supersedes:
        props["Supersedes"] = _relation(supersedes)

    # Metric anchors + idempotency key
    put("Class C Assigned", item.class_c_assigned_at, _date)
    put("Class C Decided", item.class_c_decided_at, _date)
    put("Draft Created", item.draft_created_at, _date)
    put("Review Started", item.review_started_at, _date)
    put("Review Completed", item.review_completed_at, _date)
    put("Collected At", item.collected_at, _date)
    put("Upsert Key", item.upsert_key(), _rich_text)
    put("Content Hash", item.hash, _rich_text)
    return props


# --------------------------------------------------------------------------- #
# Item → page body blocks (full text + disclaimer)
# --------------------------------------------------------------------------- #
def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def item_to_children(item: Item) -> list[dict]:
    """Page-body blocks: the not-legal-advice disclaimer callout (Class A) plus
    the full text, chunked to Notion's limits. Class B has no body (AD-5)."""
    if item.content_class is ContentClass.B or not item.full_text:
        return []
    blocks: list[dict] = []
    if item.content_class is ContentClass.A and item.interpretation:
        blocks.append({
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": [{"type": "text",
                               "text": {"content": item.interpretation.disclaimer}}],
                "icon": {"emoji": "⚖️"},
            },
        })
    text = item.full_text
    for i in range(0, len(text), _MAX_TEXT):
        if len(blocks) >= _MAX_BODY_BLOCKS:
            break
        blocks.append(_paragraph(text[i:i + _MAX_TEXT]))
    return blocks
