"""One error hierarchy the whole pipeline shares (spine convention).

TransientError  → retry with backoff (≤5), then escalate.
PermanentError  → alert + skip + structured-log; the run continues (AD-12).
"""
from __future__ import annotations


class PipelineError(Exception):
    """Base for all pipeline errors."""


class TransientError(PipelineError):
    """Recoverable — retry with backoff (5xx, timeouts, rate limits)."""


class PermanentError(PipelineError):
    """Non-recoverable for this item — alert + skip (404, schema change,
    illegal state transition, schema-validation failure)."""


class IllegalTransition(PermanentError):
    """A status transition not permitted by the state machine (AD-6)."""
