"""The single metered LLM entry point (Story 0.6, AD-7).

No component calls the raw anthropic / claude-agent-sdk client. Every call goes
through MeteredLLMClient, which writes exactly one Cost Ledger row per call.

Backends are pluggable so Phase 0 runs offline:
  - FakeLLMBackend (default): deterministic canned responses for the skeleton.
  - AnthropicBackend (opt-in): real Claude calls (lazy-imported).

The cost sink is injected (dependency inversion) so core does not depend on
platform — platform.cost_ledger provides the concrete CostSink.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class CostRow:
    timestamp: str
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    usd_cost: float
    item_id: Optional[str]
    success: bool
    tag: Optional[str] = None  # e.g. "cowork_explain_classification"


class CostSink(Protocol):
    def record(self, row: CostRow) -> None: ...


class _NullSink:
    def record(self, row: CostRow) -> None:  # pragma: no cover - trivial
        pass


# Indicative pricing (USD per 1M tokens). Config-overridable in production;
# kept here only so the Phase-0 ledger produces non-zero, plausible numbers.
_PRICING: dict[str, tuple[float, float]] = {
    "fake-model": (0.0, 0.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-opus": (15.0, 75.0),
    "claude-haiku": (0.80, 4.0),
}


def _price(model: str, in_tok: int, out_tok: int) -> float:
    in_rate, out_rate = _PRICING.get(model, (3.0, 15.0))
    return round(in_rate * in_tok / 1_000_000 + out_rate * out_tok / 1_000_000, 6)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class FakeLLMBackend:
    """Deterministic responder for the walking skeleton. A caller may register
    per-stage canned responses; otherwise a stable default is returned."""

    def __init__(self, responder: Optional[Callable[[str, str], str]] = None):
        self._responder = responder

    def complete(self, *, stage: str, model: str, prompt: str,
                 system: str = "") -> LLMResult:
        text = self._responder(stage, prompt) if self._responder else json.dumps(
            {"stub": True, "stage": stage}
        )
        # crude token estimate so the ledger has realistic-ish magnitudes
        in_tok = max(1, len(prompt) // 4)
        out_tok = max(1, len(text) // 4)
        return LLMResult(text=text, model=model, input_tokens=in_tok,
                         output_tokens=out_tok)


class AnthropicBackend:  # pragma: no cover - needs network + key
    def __init__(self, api_key: Optional[str] = None):
        try:
            from anthropic import Anthropic  # lazy import (optional dep)
        except ImportError as exc:
            raise RuntimeError(
                "anthropic not installed. `pip install legal-intel[full]`"
            ) from exc
        self._client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    def complete(self, *, stage, model, prompt, system=""):
        msg = self._client.messages.create(
            model=model,
            max_tokens=4000,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return LLMResult(
            text=text, model=model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )


def make_backend():
    if os.environ.get("LEGAL_INTEL_LLM_BACKEND", "fake").lower() == "anthropic":
        return AnthropicBackend()  # pragma: no cover
    return FakeLLMBackend()


# --------------------------------------------------------------------------- #
# Metered client
# --------------------------------------------------------------------------- #
class MeteredLLMClient:
    def __init__(self, backend=None, sink: Optional[CostSink] = None) -> None:
        self._backend = backend or make_backend()
        self._sink: CostSink = sink or _NullSink()

    def complete(self, *, stage: str, model: str, prompt: str, system: str = "",
                 item_id: Optional[str] = None, tag: Optional[str] = None) -> LLMResult:
        success = True
        try:
            result = self._backend.complete(
                stage=stage, model=model, prompt=prompt, system=system
            )
            return result
        except Exception:
            success = False
            raise
        finally:
            # Record the call even on failure (failed-call-rate alert, FR-20/21).
            in_tok = locals().get("result").input_tokens if success else 0
            out_tok = locals().get("result").output_tokens if success else 0
            self._sink.record(CostRow(
                timestamp=datetime.now(timezone.utc).isoformat(),
                stage=stage, model=model,
                input_tokens=in_tok, output_tokens=out_tok,
                usd_cost=_price(model, in_tok, out_tok),
                item_id=item_id, success=success, tag=tag,
            ))
