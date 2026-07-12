"""Structured JSON logging (Story 0.8, FR-20).

Every stage emits one JSON object per event with the required fields. No
unstructured print logging anywhere in the pipeline.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Optional, TextIO


class StructuredLogger:
    def __init__(self, stream: Optional[TextIO] = None) -> None:
        self._stream = stream or sys.stdout
        self.records: list[dict[str, Any]] = []  # kept for tests/observability

    def log(self, *, source: str, event: str, status: str,
            duration_ms: Optional[float] = None, error: Optional[str] = None,
            item_id: Optional[str] = None, **extra: Any) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "event": event,
            "status": status,
            "duration_ms": duration_ms,
            "error": error,
            "item_id": item_id,
            **extra,
        }
        self.records.append(rec)
        self._stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._stream.flush()


_default = StructuredLogger()


def get_logger() -> StructuredLogger:
    return _default
