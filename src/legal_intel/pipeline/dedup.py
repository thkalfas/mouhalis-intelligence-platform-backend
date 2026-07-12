"""Deduplication filter (Story 2.1/2.2, FR-5, AD-4/14/15/16).

Weighted signal scoring, authority-ranked merge, and precedent ownership. Phase-0
scope implements the scoring + merge + threshold routing against the in-memory set
of already-known Items; the human dedup-confirmation queue lands in Epic 2/8.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from ..core.config import AppConfig
from ..core.models import ContentClass, Item, SourceLink

AUTO_MERGE = 0.95
CONFIRM_LOW = 0.70


@dataclass
class DedupOutcome:
    item: Item
    merged_into: Optional[Item]  # existing Item this was merged into, if any
    score: float
    needs_confirmation: bool


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score(candidate: Item, existing: Item) -> float:
    """Aggregate weighted duplicate score (spec §3.3). Highest single signal
    wins rather than summing, matching the 'each gives partial score' intent."""
    signals: list[float] = []
    if (candidate.source_id == existing.source_id
            and candidate.source_name == existing.source_name):
        signals.append(1.0)
    if candidate.hash and candidate.hash == existing.hash:
        signals.append(0.95)
    if _title_similarity(candidate.title, existing.title) > 0.85:
        signals.append(0.6)
    if (candidate.authority == existing.authority
            and candidate.date_published == existing.date_published):
        signals.append(0.5)
    return max(signals, default=0.0)


def best_match(candidate: Item, known: list[Item]) -> tuple[Optional[Item], float]:
    best, best_score = None, 0.0
    for other in known:
        s = score(candidate, other)
        if s > best_score:
            best, best_score = other, s
    return best, best_score


def merge(primary: Item, secondary: Item, cfg: AppConfig) -> Item:
    """Merge secondary into the higher-authority Item, keeping all source links
    and preserving commentary (FR-5, AD authority hierarchy)."""
    rank_p = cfg.authority_rank(primary.source_name)
    rank_s = cfg.authority_rank(secondary.source_name)
    winner, loser = (primary, secondary) if rank_p <= rank_s else (secondary, primary)

    # A re-ingest of the winner's own source adds no link; and never add the same
    # source URL twice (keeps re-runs idempotent, AD-4).
    same_source = (loser.source_id == winner.source_id
                   and loser.source_name == winner.source_name)
    already_linked = any(s.url == loser.url for s in winner.additional_sources)
    if not same_source and not already_linked:
        winner.additional_sources.append(
            SourceLink(source=loser.source_name, url=loser.url,
                       collected_at=loser.collected_at)
        )
    # Fall back to loser's full text only if the winner lacks it.
    if not winner.full_text and loser.full_text:
        winner.full_text = loser.full_text
        winner.snippet = loser.snippet
        winner.hash = loser.hash
    if loser.external_commentary and not winner.external_commentary:
        winner.external_commentary = loser.external_commentary
    return winner


def dedup(candidate: Item, known: list[Item], cfg: AppConfig) -> DedupOutcome:
    match, s = best_match(candidate, known)
    if match is not None and s >= AUTO_MERGE:
        merged = merge(match, candidate, cfg)
        merged.dedup_score = s
        return DedupOutcome(item=merged, merged_into=match, score=s,
                            needs_confirmation=False)
    candidate.dedup_score = s
    if match is not None and CONFIRM_LOW <= s < AUTO_MERGE:
        return DedupOutcome(item=candidate, merged_into=None, score=s,
                            needs_confirmation=True)
    return DedupOutcome(item=candidate, merged_into=None, score=s,
                        needs_confirmation=False)
