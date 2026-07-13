"""Deduplication & merge filter (Epic 2 — FR-5, AD-14/15/16).

One Item per Legal Event. Weighted signals (config-driven, AD-8) produce an
aggregate ``dedup_score``; the configured thresholds route it to auto-merge, a
human confirmation queue, or "distinct". Merges keep the most authoritative
source's content while preserving every source link (AD authority hierarchy),
and a merge that changes an already-interpreted Item enqueues re-interpretation
instead of mutating an Approved reading (AD-16). Superseding versions (e.g. a
corrigendum) become a new Item linked to — and retiring — their target (AD-15).

Identity note: the surviving Item always keeps the *first-seen* identity
(`source_id`/`source_name`/`hash`) and its `page_id`, so the upsert key is stable
and re-runs never create a second page regardless of source arrival order
(AD-14). Authority governs *content* fields via `primary_source`, not identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from ..core import state_machine as sm
from ..core.config import AppConfig
from ..core.models import Item, ItemStatus, SourceLink
from ..core.notion_gateway import NotionGateway

# Statuses at/after a produced interpretation — a content change here must
# trigger re-interpretation rather than a silent in-place edit (AD-16).
_INTERPRETED_STATES = {
    ItemStatus.CLASS_A_DRAFT_INTERPRETATION,
    ItemStatus.APPROVED,
    ItemStatus.REQUIRES_ACTION,
}


@dataclass
class DedupOutcome:
    item: Item
    merged_into: Optional[Item]  # the existing Item merged into / suspected duplicate of
    score: float
    needs_confirmation: bool = False
    superseded_target: Optional[Item] = None  # target retired to Superseded (AD-15)
    reinterpret: bool = False  # merge changed an already-interpreted Item (AD-16)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _topic_overlap(a: Item, b: Item) -> float:
    """Jaccard overlap of Topic sets. 0 when either is untagged — in the normal
    pipeline order tagging runs *after* dedup, so this signal only contributes
    when scoring against already-tagged Items."""
    sa, sb = set(a.topics), set(b.topics)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def score(candidate: Item, existing: Item, cfg: AppConfig) -> float:
    """Aggregate weighted duplicate score (spec §3.3): each matching signal adds
    its weight, capped at 1.0 ('each gives a partial score')."""
    w = cfg.dedup.weights
    th = cfg.dedup.thresholds
    total = 0.0
    if (candidate.source_id == existing.source_id
            and candidate.source_name == existing.source_name):
        total += w.exact_source_id
    if candidate.hash and candidate.hash == existing.hash:
        total += w.text_hash
    if _title_similarity(candidate.title, existing.title) >= th.title_similarity_min:
        total += w.title_similarity
    if (existing.authority and candidate.authority == existing.authority
            and candidate.date_published is not None
            and candidate.date_published == existing.date_published):
        total += w.authority_date
    if _topic_overlap(candidate, existing) >= th.topic_overlap_min:
        total += w.topic_entity_overlap
    return min(total, 1.0)


def best_match(candidate: Item, known: list[Item],
               cfg: AppConfig) -> tuple[Optional[Item], float]:
    best, best_score = None, 0.0
    for other in known:
        if other is candidate:
            continue
        s = score(candidate, other, cfg)
        if s > best_score:
            best, best_score = other, s
    return best, best_score


# --------------------------------------------------------------------------- #
# Merge (authority-ranked, identity-preserving)
# --------------------------------------------------------------------------- #
def _add_link(item: Item, source: str, url: str, collected_at) -> None:
    """Record a contributing source URL, unless it is empty, is the current
    primary URL, or is already linked (keeps re-runs idempotent, AD-4)."""
    if not url or url == item.url:
        return
    if any(s.url == url for s in item.additional_sources):
        return
    item.additional_sources.append(
        SourceLink(source=source, url=url, collected_at=collected_at)
    )


def merge(existing: Item, candidate: Item, cfg: AppConfig) -> tuple[Item, bool]:
    """Merge ``candidate`` into ``existing`` (which keeps its page_id/identity).
    Returns (survivor, content_changed). ``content_changed`` is True when an
    authoritative field or full text was replaced — the AD-16 re-interpretation
    signal."""
    survivor = existing
    cur_rank = cfg.authority_rank(survivor.primary_source or survivor.source_name)
    cand_rank = cfg.authority_rank(candidate.source_name)
    changed = False

    if cand_rank < cur_rank:
        # Candidate is more authoritative → its content wins; the displaced
        # primary's URL is preserved as an additional source.
        old_source = survivor.primary_source or survivor.source_name
        old_url, old_collected = survivor.url, survivor.collected_at
        changed = (
            survivor.title != candidate.title
            or survivor.url != candidate.url
            or (bool(candidate.full_text) and candidate.full_text != survivor.full_text)
        )
        survivor.title = candidate.title
        survivor.type = candidate.type
        survivor.authority = candidate.authority
        if candidate.jurisdiction:
            survivor.jurisdiction = candidate.jurisdiction
        if candidate.date_published:
            survivor.date_published = candidate.date_published
        if candidate.date_effective:
            survivor.date_effective = candidate.date_effective
        survivor.url = candidate.url
        survivor.primary_source = candidate.source_name
        if candidate.full_text:
            survivor.full_text = candidate.full_text
            survivor.snippet = candidate.snippet
        _add_link(survivor, old_source, old_url, old_collected)
    else:
        # Lower/equal authority: only fill a full-text gap (fallback), keep links.
        _add_link(survivor, candidate.source_name, candidate.url, candidate.collected_at)
        if not survivor.full_text and candidate.full_text:
            survivor.full_text = candidate.full_text
            survivor.snippet = candidate.snippet
            changed = True

    # Commercial/editorial commentary never wins metadata but is preserved.
    if candidate.external_commentary and not survivor.external_commentary:
        survivor.external_commentary = candidate.external_commentary

    reinterpret = changed and survivor.status in _INTERPRETED_STATES
    return survivor, reinterpret


# --------------------------------------------------------------------------- #
# Supersession (AD-15)
# --------------------------------------------------------------------------- #
def _item_identity(item: Item) -> str:
    return item.page_id or item.dedup_key()


def _find_supersede_target(candidate: Item, known: list[Item]) -> Optional[Item]:
    """Locate the Item a superseding version replaces, by the raw ref the source
    carried (e.g. a corrigendum's base CELEX), preferring same-source matches."""
    ref = candidate.supersedes_ref
    same_source = [k for k in known if k.source_name == candidate.source_name
                   and k.source_id == ref]
    if same_source:
        return same_source[0]
    any_source = [k for k in known if k.source_id == ref]
    return any_source[0] if any_source else None


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def dedup(candidate: Item, known: list[Item], cfg: AppConfig) -> DedupOutcome:
    # 1) Supersession is resolved before duplicate detection (AD-15): a new
    #    version is a distinct Item that retires its predecessor.
    if candidate.supersedes_ref:
        target = _find_supersede_target(candidate, known)
        if target is not None:
            target_id = _item_identity(target)
            precedent = [target_id, *[p for p in target.supersedes if p != target_id]]
            candidate.supersedes = precedent
            # Inherit the target's Topics (union; tagging may add more).
            candidate.topics = list(dict.fromkeys([*target.topics, *candidate.topics]))
            candidate.supersedes_ref = None
            return DedupOutcome(item=candidate, merged_into=None, score=0.0,
                                superseded_target=target)
        # No target found → treat as an ordinary new Item.
        candidate.supersedes_ref = None

    # 2) Duplicate detection.
    match, s = best_match(candidate, known, cfg)
    th = cfg.dedup.thresholds
    if match is not None and s >= th.auto_merge:
        survivor, reinterpret = merge(match, candidate, cfg)
        survivor.dedup_score = max(survivor.dedup_score or 0.0, s)
        return DedupOutcome(item=survivor, merged_into=match, score=s,
                            reinterpret=reinterpret)

    candidate.dedup_score = s
    if match is not None and th.confirm_low <= s < th.auto_merge:
        # Probable duplicate → human confirmation queue (AD-5, Story 2.3).
        return DedupOutcome(item=candidate, merged_into=match, score=s,
                            needs_confirmation=True)
    return DedupOutcome(item=candidate, merged_into=None, score=s)


# --------------------------------------------------------------------------- #
# Human dedup-confirmation resolution (Story 2.3, HUMAN actor)
# --------------------------------------------------------------------------- #
def confirm_merge(candidate: Item, target: Item, cfg: AppConfig,
                  gateway: NotionGateway) -> Item:
    """Reviewer confirms a probable duplicate: merge the candidate's content into
    the target, retire the candidate page (Archived), persist both."""
    sm.assert_transition(candidate.status, ItemStatus.ARCHIVED, sm.Actor.HUMAN)
    survivor, _ = merge(target, candidate, cfg)
    candidate.status = ItemStatus.ARCHIVED
    gateway.upsert_item(candidate)
    gateway.upsert_item(survivor)
    return survivor


def reject_as_distinct(candidate: Item, gateway: NotionGateway) -> Item:
    """Reviewer rejects the merge: the candidate is a distinct Legal Event and
    re-enters the pipeline at triage."""
    sm.assert_transition(candidate.status, ItemStatus.AWAITING_TRIAGE, sm.Actor.HUMAN)
    candidate.status = ItemStatus.AWAITING_TRIAGE
    gateway.upsert_item(candidate)
    return candidate
