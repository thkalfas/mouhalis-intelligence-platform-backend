"""Run the Phase-0 walking skeleton end-to-end from the CLI.

    python -m legal_intel

Uses the local (offline) Notion backend and the fake LLM by default, so it runs
with no token or network — the Phase-0 validation gate.
"""
from __future__ import annotations

import json
import sys

# Greek titles must print on any console; Windows defaults to cp1252 and would
# otherwise crash on the first Greek character. Force UTF-8 on stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

from .adapters.registry import build_enabled_adapters
from .core.models import Item
from .pipeline.runner import PipelineRunner


def main() -> None:
    runner = PipelineRunner()
    # Config-driven wiring (AD-3, AD-8): run whichever sources are enabled in
    # sources.yaml. Offline, that is just FakeSource; enabling a real Tier-1
    # adapter is a config flip (plus its network prerequisites).
    adapters = build_enabled_adapters(runner.cfg)
    ingested = persisted = errors = 0
    by_class: dict[str, int] = {}
    for adapter in adapters:
        report = runner.run(adapter)
        ingested += report.ingested
        persisted += report.persisted
        errors += report.errors
        for cls, n in report.by_class.items():
            by_class[cls] = by_class.get(cls, 0) + n

    print("\n=== Run report ===")
    print(f"  sources  : {[a.name for a in adapters]}")
    print(f"  ingested : {ingested}")
    print(f"  persisted: {persisted}  (Items in Notion: {runner.gateway.count()})")
    print(f"  by class : {by_class}")
    print(f"  errors   : {errors}")

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
