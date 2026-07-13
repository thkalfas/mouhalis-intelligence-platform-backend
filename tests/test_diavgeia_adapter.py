"""Story 1.3 — Δι@ύγεια adapter (offline, fixture-driven)."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from legal_intel.adapters.diavgeia import DiavgeiaAdapter
from legal_intel.core.config import SourceConfig
from legal_intel.platform.http import HttpClient, HttpResponse
from legal_intel.platform.logging import get_logger

ENDPOINT = "https://diavgeia.gov.gr/opendata"
_PDF = b"%PDF-1.7 decision body"
_GOOD_CHECKSUM = hashlib.sha256(_PDF).hexdigest()


def _search_payload(checksum: str) -> dict:
    return {
        "decisions": [
            {
                "ada": "ΩΞΨ1234-ΑΒΓ",
                "subject": "Απόφαση Επιτροπής Ανταγωνισμού για κάθετες συμφωνίες",
                "decisionType": {"label": "Απόφαση"},
                "organization": {"label": "Επιτροπή Ανταγωνισμού"},
                "issueDate": "2026-07-10",
                "documentUrl": "https://diavgeia.gov.gr/doc/decision.pdf",
                "documentChecksum": checksum,
            }
        ]
    }


class _RoutingTransport:
    def __init__(self, checksum: str = _GOOD_CHECKSUM) -> None:
        self.checksum = checksum
        self.calls: list[str] = []

    def __call__(self, method, url, *, params=None, headers=None) -> HttpResponse:
        self.calls.append(url)
        if url.endswith("/search"):
            body = json.dumps(_search_payload(self.checksum)).encode("utf-8")
            return HttpResponse(200, url, body, {"content-type": "application/json"})
        return HttpResponse(200, url, _PDF, {"content-type": "application/pdf"})


def _adapter(transport):
    cfg = SourceConfig(
        name="Διαύγεια", tier=1, endpoint=ENDPOINT, cadence="6h", authority_rank=1,
        options={"organization_uids": ["100026000"], "lookback_days": 30},
    )
    return DiavgeiaAdapter(cfg, HttpClient(transport, sleep=lambda s: None),
                           now=date(2026, 7, 13))


def test_fetch_maps_decision_fields():
    records = list(_adapter(_RoutingTransport()).fetch())
    assert len(records) == 1
    rec = records[0]
    assert rec.source_id == "ΩΞΨ1234-ΑΒΓ"
    assert rec.title.startswith("Απόφαση Επιτροπής")
    assert rec.type == "Απόφαση"
    assert rec.authority == "Επιτροπή Ανταγωνισμού"
    assert rec.date_published == date(2026, 7, 10)
    assert rec.raw_body == _PDF
    assert rec.content_type == "application/pdf"


def test_search_uses_org_uid_and_window():
    transport = _RoutingTransport()
    list(_adapter(transport).fetch())
    # first call is the search with org uid param
    assert transport.calls[0].endswith("/search")


def test_checksum_mismatch_is_logged_not_fatal():
    logger = get_logger()
    before = len(logger.records)
    records = list(_adapter(_RoutingTransport(checksum="0" * 64)).fetch())
    assert len(records) == 1  # still emitted
    assert records[0].raw_body == _PDF
    mismatch = [r for r in logger.records[before:] if r.get("status") == "mismatch"]
    assert mismatch, "expected a checksum mismatch log line"


def test_no_org_uids_is_degraded_empty():
    cfg = SourceConfig(name="Διαύγεια", tier=1, endpoint=ENDPOINT, cadence="6h",
                       authority_rank=1, options={})
    adapter = DiavgeiaAdapter(cfg, HttpClient(_RoutingTransport(), sleep=lambda s: None))
    assert list(adapter.fetch()) == []
