"""Cost Ledger — the CostSink implementation + monthly reporting (Story 0.6, FR-21).

Authoritative store in production is a Notion auxiliary "Cost Ledger" DB; writes
buffer to a local append-only JSONL file and flush, so a crash loses at most the
unflushed tail. Phase 0 uses the local buffer only.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ..core.llm_client import CostRow
from .alerting import AlertLevel, get_alerter

SINGLE_ITEM_ALERT_USD = 1.0


class CostLedger:
    """Implements core.llm_client.CostSink."""

    def __init__(self, buffer_path: Optional[Path] = None,
                 baseline_monthly_usd: float = 30.0) -> None:
        self._rows: list[CostRow] = []
        self._buffer_path = buffer_path
        self._baseline = baseline_monthly_usd

    def record(self, row: CostRow) -> None:
        self._rows.append(row)
        if self._buffer_path:
            self._buffer_path.parent.mkdir(parents=True, exist_ok=True)
            with self._buffer_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row.__dict__, ensure_ascii=False) + "\n")
        # Per-item runaway guard (spec §12 alert threshold).
        if row.usd_cost > SINGLE_ITEM_ALERT_USD:
            get_alerter().fire(
                AlertLevel.WARNING,
                f"Single LLM call cost ${row.usd_cost} > ${SINGLE_ITEM_ALERT_USD}",
                stage=row.stage, model=row.model, item_id=row.item_id,
            )

    # -- reporting ---------------------------------------------------------- #
    @property
    def rows(self) -> list[CostRow]:
        return list(self._rows)

    def total_usd(self) -> float:
        return round(sum(r.usd_cost for r in self._rows), 6)

    def failed_call_rate(self) -> float:
        if not self._rows:
            return 0.0
        failed = sum(1 for r in self._rows if not r.success)
        return failed / len(self._rows)

    def monthly_report(self) -> dict:
        by_stage: dict[str, float] = defaultdict(float)
        by_model: dict[str, float] = defaultdict(float)
        for r in self._rows:
            by_stage[r.stage] += r.usd_cost
            by_model[r.model] += r.usd_cost
        total = self.total_usd()
        report = {
            "total_usd": total,
            "by_stage": {k: round(v, 6) for k, v in by_stage.items()},
            "by_model": {k: round(v, 6) for k, v in by_model.items()},
            "calls": len(self._rows),
            "failed_call_rate": round(self.failed_call_rate(), 4),
        }
        if total > 2 * self._baseline:
            get_alerter().fire(
                AlertLevel.WARNING,
                f"Monthly cost ${total} > 2x baseline ${self._baseline}",
            )
        if self.failed_call_rate() > 0.05:
            get_alerter().fire(
                AlertLevel.CRITICAL,
                f"Failed LLM-call rate {report['failed_call_rate']} > 5%",
            )
        return report
