"""Source-health board writer (offline, local backend)."""
from __future__ import annotations

from datetime import datetime, timezone

from legal_intel.platform.source_health import (LocalSourceHealthBackend,
                                                SourceHealth,
                                                SourceHealthWriter,
                                                status_from_report)

_NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


def test_status_from_report():
    assert status_from_report(17, 0) == "Success"
    assert status_from_report(17, 5) == "Degraded"
    assert status_from_report(0, 5) == "Failure"


def test_writer_upserts_by_source_name():
    backend = LocalSourceHealthBackend()
    writer = SourceHealthWriter(backend)
    assert writer.active
    writer.record(SourceHealth(source="EUR-Lex", tier=1, adapter="eurlex",
                               enabled=True, status="Degraded", items_collected=17,
                               errors=5, last_run=_NOW))
    writer.record(SourceHealth(source="EUR-Lex", tier=1, adapter="eurlex",
                               enabled=True, status="Success", items_collected=20,
                               errors=0, last_run=_NOW))  # same key → overwrite
    assert len(backend.rows) == 1
    assert backend.rows["EUR-Lex"].status == "Success"
    assert backend.rows["EUR-Lex"].items_collected == 20


def test_writer_noop_when_no_backend():
    # No Notion board configured → disabled writer, record() is a harmless no-op.
    writer = SourceHealthWriter(backend=None)
    assert writer.active is False
    writer.record(SourceHealth(source="X", tier=1, adapter="a", enabled=False,
                               status="Not run"))  # must not raise
