"""Story 1.2 — EUR-Lex / CELLAR adapter (offline, fixture-driven)."""
from __future__ import annotations

import json
from datetime import date

from legal_intel.adapters.eurlex import EurLexAdapter
from legal_intel.core.config import SourceConfig
from legal_intel.platform.http import HttpClient, HttpResponse

SPARQL_ENDPOINT = "http://publications.europa.eu/webapi/rdf/sparql"

_SPARQL_RESULT = {
    "results": {
        "bindings": [
            {
                "work": {"value": "http://.../work/1"},
                "celex": {"value": "32026R0001"},
                "title": {"value": "Κανονισμός ιχνηλασιμότητας καπνικών"},
                "date": {"value": "2026-07-08"},
                "type": {"value": "Regulation"},
            },
            {
                "work": {"value": "http://.../work/2"},
                "celex": {"value": "32024R1679R(01)"},  # corrigendum
                "title": {"value": "Διορθωτικό κανονισμού 1679"},
                "date": {"value": "2026-07-07"},
                "type": {"value": "Regulation"},
            },
        ]
    }
}


class _RoutingTransport:
    def __init__(self, fail_fulltext_for: set[str] | None = None) -> None:
        self.fail = fail_fulltext_for or set()
        self.calls: list[str] = []

    def __call__(self, method, url, *, params=None, headers=None) -> HttpResponse:
        self.calls.append(url)
        if "sparql" in url:
            return HttpResponse(200, url, json.dumps(_SPARQL_RESULT).encode(),
                                {"content-type": "application/sparql-results+json"})
        # celex REST full-text fetch
        celex = url.rsplit("/", 1)[-1]
        if celex in self.fail:
            return HttpResponse(404, url, b"", {})
        html = f"<html><body><p>Πλήρες κείμενο {celex}.</p></body></html>"
        return HttpResponse(200, url, html.encode("utf-8"),
                            {"content-type": "text/html; charset=utf-8"})


def _adapter(transport):
    cfg = SourceConfig(
        name="EUR-Lex", tier=1, endpoint=SPARQL_ENDPOINT, cadence="30m",
        authority_rank=1,
        options={"lookback_days": 7, "resource_types": ["REG", "DIR"],
                 "eurovoc_descriptors": ["tobacco industry", "foodstuff"]},
    )
    http = HttpClient(transport, sleep=lambda s: None)
    return EurLexAdapter(cfg, http, now=date(2026, 7, 13))


def test_build_query_is_config_driven():
    q = _adapter(_RoutingTransport()).build_query()
    assert "resource-type/REG" in q and "resource-type/DIR" in q
    assert '"2026-07-06"^^xsd:date' in q  # now - 7 days
    assert '"tobacco industry"' in q and '"foodstuff"' in q
    assert "LIMIT 100" in q


def test_fetch_yields_records_with_fulltext():
    records = list(_adapter(_RoutingTransport()).fetch())
    assert len(records) == 2
    first = records[0]
    assert first.source_id == "32026R0001"
    assert first.source_name == "EUR-Lex"
    assert first.date_published == date(2026, 7, 8)
    assert "CELEX:32026R0001" in first.url
    assert first.content_type.startswith("text/html")
    assert "Πλήρες κείμενο 32026R0001" in first.raw_body.decode("utf-8")


def test_corrigendum_carries_supersedes_ref():
    records = list(_adapter(_RoutingTransport()).fetch())
    corr = records[1]
    assert corr.source_id == "32024R1679R(01)"
    assert corr.raw_metadata["supersedes_ref"] == "32024R1679"


def test_fulltext_failure_is_degraded_not_fatal():
    # 404 on the full-text fetch must not drop the record — identity still emits.
    transport = _RoutingTransport(fail_fulltext_for={"32026R0001"})
    records = list(_adapter(transport).fetch())
    assert len(records) == 2
    assert records[0].raw_body is None  # full text degraded
    assert records[0].source_id == "32026R0001"  # but the event is still captured
