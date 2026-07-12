"""Alerting hook (Story 0.8, FR-20, AD-12).

Fires on breakage/anomaly conditions. MVP dispatches to console; the channel is
pluggable to Slack/email later without touching callers.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from .logging import get_logger


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alerter:
    def __init__(self, dispatch: Optional[Callable[[AlertLevel, str, dict], None]] = None):
        self._dispatch = dispatch
        self.alerts: list[tuple[AlertLevel, str, dict]] = []  # for tests

    def fire(self, level: AlertLevel, message: str, **context) -> None:
        self.alerts.append((level, message, context))
        get_logger().log(
            source="alerting", event="alert", status=level.value,
            error=message if level is AlertLevel.CRITICAL else None,
            **context,
        )
        if self._dispatch:
            self._dispatch(level, message, context)


_default = Alerter()


def get_alerter() -> Alerter:
    return _default
