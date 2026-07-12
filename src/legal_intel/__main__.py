"""Run the Phase-0 walking skeleton end-to-end from the CLI.

    python -m legal_intel

Uses the local (offline) Notion backend and the fake LLM by default, so it runs
with no token or network — the Phase-0 validation gate.
"""
from __future__ import annotations

import json

from .adapters.fake import FakeSourceAdapter
from .core.models import Item
from .pipeline.runner import PipelineRunner


def main() -> None:
    runner = PipelineRunner()
    report = runner.run(FakeSourceAdapter())

    print("\n=== Run report ===")
    print(f"  ingested : {report.ingested}")
    print(f"  persisted: {report.persisted}  (Items in Notion: {runner.gateway.count()})")
    print(f"  by class : {report.by_class}")
    print(f"  errors   : {report.errors}")

    print("\n=== Items in the System of Record ===")
    for payload in runner.gateway.all_items():
        item = Item.model_validate(payload)
        cls = item.content_class.value if item.content_class else "?"
        has_text = "full-text" if item.full_text else "no-text"
        has_interp = "interpreted" if item.interpretation else "-"
        print(f"  [{cls}] {item.status.value:32} {has_text:9} {has_interp:12} {item.title[:60]}")

    print("\n=== Cost ledger (monthly report) ===")
    print(json.dumps(runner.ledger.monthly_report(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
