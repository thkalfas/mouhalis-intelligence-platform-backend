"""Run the collection pipeline end-to-end from the CLI.

    python -m legal_intel

Runs one full pass over every source enabled in ``config/sources.yaml``. With no
configuration it uses the local (offline) Notion backend and the fake LLM, so it
runs with no token or network — the validation gate. Point it at the real
backends by setting the environment variables in ``.env`` (see ``.env.example``):
``LEGAL_INTEL_NOTION_BACKEND=notion`` + ``NOTION_TOKEN``/``NOTION_DATABASE_ID``
and ``LEGAL_INTEL_LLM_BACKEND=anthropic`` + ``ANTHROPIC_API_KEY``.

Schedule this command (Windows Task Scheduler / cron / systemd timer) to run it
on the source cadences; one invocation is idempotent (upsert-by-key, AD-14).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Greek titles must print on any console; Windows defaults to cp1252 and would
# otherwise crash on the first Greek character. Force UTF-8 on stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a ``.env`` in the current dir (secrets stay out
    of the repo). Minimal + dependency-free; a real host may inject env vars
    directly instead. Existing environment variables win."""
    path = Path.cwd() / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

from datetime import datetime, timezone

from .adapters.registry import build_adapter
from .core.models import Item
from .pipeline.runner import PipelineRunner
from .platform.source_health import (SourceHealth, SourceHealthWriter,
                                     status_from_report)


def main() -> None:
    runner = PipelineRunner()
    health = SourceHealthWriter()  # no-op unless the Notion board is configured
    # Config-driven wiring (AD-3, AD-8): run whichever sources are enabled in
    # sources.yaml. Offline, that is just FakeSource; enabling a real adapter is
    # a config flip (plus its network prerequisites). Each source's outcome is
    # recorded to the Source Health board (FR-20).
    sources = runner.cfg.enabled_sources()
    ingested = persisted = errors = 0
    by_class: dict[str, int] = {}
    for src in sources:
        now = datetime.now(timezone.utc)
        try:
            report = runner.run(build_adapter(src))
            status = status_from_report(report.persisted, report.errors)
            note = f"{report.persisted}/{report.ingested} collected, {report.errors} errored"
        except Exception as exc:  # a whole-source failure isolates here (AD-12)
            report = None
            status, note = "Failure", str(exc)[:400]
            errors += 1
            runner.log.log(source=src.name, event="source_run", status="failed",
                           error=str(exc))
        health.record(SourceHealth(
            source=src.name, tier=src.tier, adapter=src.adapter or "", enabled=src.enabled,
            status=status, cadence=src.cadence, authority_rank=src.authority_rank,
            items_collected=(report.persisted if report else 0),
            filtered=(report.filtered if report else 0),
            errors=(report.errors if report else 1), notes=note, last_run=now))
        if report is not None:
            ingested += report.ingested
            persisted += report.persisted
            errors += report.errors
            for cls, n in report.by_class.items():
                by_class[cls] = by_class.get(cls, 0) + n

    print("\n=== Run report ===")
    print(f"  sources  : {[s.name for s in sources]}"
          + ("  [health board active]" if health.active else ""))
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
