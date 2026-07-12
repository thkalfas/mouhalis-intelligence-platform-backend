"""The single authority on allowed status transitions and who may perform them
(Story 0.2, AD-6, AD-13).

Two actor kinds:
  - PIPELINE  : automated stages. May perform automatic transitions only.
  - HUMAN     : reviewers acting in Notion. Own approve/reject/reclassify/confirm.

An automated caller attempting a human-only transition, or any undefined
transition, raises IllegalTransition (a PermanentError) — never a silent apply.
"""
from __future__ import annotations

from enum import Enum

from .errors import IllegalTransition
from .models import ItemStatus as S


class Actor(str, Enum):
    PIPELINE = "pipeline"
    HUMAN = "human"


# (from, to) -> actor allowed to perform it.
# Pipeline-owned automatic transitions:
_PIPELINE_TRANSITIONS: set[tuple[S, S]] = {
    (S.NEW, S.AWAITING_TRIAGE),
    (S.AWAITING_TRIAGE, S.CLASS_A_AWAITING_INTERPRETATION),
    (S.AWAITING_TRIAGE, S.CLASS_B_INDEXED),
    (S.AWAITING_TRIAGE, S.CLASS_C_AWAITING_HUMAN_REVIEW),
    (S.AWAITING_TRIAGE, S.AWAITING_DEDUP_CONFIRMATION),
    (S.NEW, S.AWAITING_DEDUP_CONFIRMATION),
    (S.CLASS_A_AWAITING_INTERPRETATION, S.CLASS_A_DRAFT_INTERPRETATION),
    # Superseded may be applied to any Item, including terminal ones (AD-15).
    (S.APPROVED, S.SUPERSEDED),
    (S.REQUIRES_ACTION, S.SUPERSEDED),
    (S.CLASS_A_DRAFT_INTERPRETATION, S.SUPERSEDED),
    (S.CLASS_B_INDEXED, S.SUPERSEDED),
    # Re-interpretation after a late merge (AD-16) or reject.
    (S.APPROVED, S.CLASS_A_AWAITING_INTERPRETATION),
}

# Human-only transitions (reviewers in Notion, WF1/WF2/WF3):
_HUMAN_TRANSITIONS: set[tuple[S, S]] = {
    # WF1 — Class C relevance review
    (S.CLASS_C_AWAITING_HUMAN_REVIEW, S.CLASS_A_AWAITING_INTERPRETATION),
    (S.CLASS_C_AWAITING_HUMAN_REVIEW, S.CLASS_B_INDEXED),
    # Dedup confirmation
    (S.AWAITING_DEDUP_CONFIRMATION, S.AWAITING_TRIAGE),
    (S.AWAITING_DEDUP_CONFIRMATION, S.ARCHIVED),
    # WF2 — interpretation review
    (S.CLASS_A_DRAFT_INTERPRETATION, S.APPROVED),
    (S.CLASS_A_DRAFT_INTERPRETATION, S.REJECTED),
    (S.REJECTED, S.CLASS_A_AWAITING_INTERPRETATION),
    # WF3 — post-approval
    (S.APPROVED, S.REQUIRES_ACTION),
    (S.APPROVED, S.ARCHIVED),
    (S.REQUIRES_ACTION, S.ARCHIVED),
    # Reclassify B -> A (in-place re-fetch, AD-11)
    (S.CLASS_B_INDEXED, S.CLASS_A_AWAITING_INTERPRETATION),
}


def can_transition(src: S, dst: S, actor: Actor) -> bool:
    if actor is Actor.PIPELINE:
        return (src, dst) in _PIPELINE_TRANSITIONS
    # Humans may also perform any pipeline transition; pipeline may NOT perform
    # human-only ones — the asymmetry is the point of AD-6.
    return (src, dst) in _HUMAN_TRANSITIONS or (src, dst) in _PIPELINE_TRANSITIONS


def assert_transition(src: S, dst: S, actor: Actor) -> None:
    if not can_transition(src, dst, actor):
        raise IllegalTransition(
            f"{actor.value} may not transition {src.value!r} -> {dst.value!r}"
        )


def is_human_only(src: S, dst: S) -> bool:
    return (src, dst) in _HUMAN_TRANSITIONS and (src, dst) not in _PIPELINE_TRANSITIONS
