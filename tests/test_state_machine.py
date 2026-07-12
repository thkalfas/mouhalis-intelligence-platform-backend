"""State machine — split transition ownership (Story 0.2, AD-6)."""
import pytest

from legal_intel.core import state_machine as sm
from legal_intel.core.errors import IllegalTransition
from legal_intel.core.models import ItemStatus as S


def test_pipeline_may_do_automatic_transitions():
    sm.assert_transition(S.NEW, S.AWAITING_TRIAGE, sm.Actor.PIPELINE)
    sm.assert_transition(
        S.CLASS_A_AWAITING_INTERPRETATION,
        S.CLASS_A_DRAFT_INTERPRETATION,
        sm.Actor.PIPELINE,
    )


def test_pipeline_may_not_approve():
    # Approve is human-only (AD-6) — the pipeline must be refused.
    with pytest.raises(IllegalTransition):
        sm.assert_transition(
            S.CLASS_A_DRAFT_INTERPRETATION, S.APPROVED, sm.Actor.PIPELINE
        )


def test_human_may_approve():
    sm.assert_transition(
        S.CLASS_A_DRAFT_INTERPRETATION, S.APPROVED, sm.Actor.HUMAN
    )


def test_undefined_transition_rejected():
    with pytest.raises(IllegalTransition):
        sm.assert_transition(S.NEW, S.APPROVED, sm.Actor.HUMAN)


def test_superseded_allowed_on_terminal_item():
    # AD-15: a corrigendum can supersede an already-Approved Item.
    sm.assert_transition(S.APPROVED, S.SUPERSEDED, sm.Actor.PIPELINE)


def test_reclassify_b_to_a_is_human_only():
    assert sm.is_human_only(
        S.CLASS_B_INDEXED, S.CLASS_A_AWAITING_INTERPRETATION
    )
