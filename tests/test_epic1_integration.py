"""Epic 1 integration — a real Tier-1 adapter's records flow through the whole
pipeline (adapter → normalize/extract → dedup → tag → triage → interpret) into
the store, offline via fixture HTTP. Proves the seam the fake adapter stood in for.
"""
from __future__ import annotations

import json
from datetime import date

from legal_intel.adapters.eurlex import EurLexAdapter
from legal_intel.core.config import SourceConfig
from legal_intel.core.models import ContentClass, Item
from legal_intel.platform.http import HttpClient, HttpResponse

_SPARQL = {
    "results": {"bindings": [{
        "work": {"value": "http://.../w/1"},
        "celex": {"value": "32026R0777"},
        "title": {"value": "Κανονισμός ιχνηλασιμότητας καπνικών"},
        "date": {"value": "2026-07-08"},
        "type": {"value": "Regulation"},
    }]}
}
# Full text mentions KAD 46.35 → deterministic Class A (kad_direct_mention rule).
_HTML = (
    "<html><body><p>Ο παρών κανονισμός αφορά τη χονδρική εμπορία προϊόντων "
    "καπνού (ΚΑΔ 46.35) και θεσπίζει υποχρεώσεις ιχνηλασιμότητας.</p></body></html>"
)


def _transport(method, url, *, params=None, headers=None) -> HttpResponse:
    if "sparql" in url:
        return HttpResponse(200, url, json.dumps(_SPARQL).encode("utf-8"),
                            {"content-type": "application/sparql-results+json"})
    return HttpResponse(200, url, _HTML.encode("utf-8"),
                        {"content-type": "text/html; charset=utf-8"})


def test_eurlex_records_flow_end_to_end(runner, gateway):
    cfg = SourceConfig(name="EUR-Lex", tier=1,
                       endpoint="http://publications.europa.eu/webapi/rdf/sparql",
                       cadence="30m", authority_rank=1, adapter="eurlex",
                       options={"resource_types": ["REG"]})
    adapter = EurLexAdapter(cfg, HttpClient(_transport, sleep=lambda s: None),
                            now=date(2026, 7, 13))

    report = runner.run(adapter)
    assert report.ingested == 1
    assert gateway.count() == 1

    item = Item.model_validate(gateway.all_items()[0])
    assert item.source_id == "32026R0777"
    assert item.source_name == "EUR-Lex"
    # HTML body was extracted to plain text by normalization.
    assert "ιχνηλασιμότητας" in item.full_text
    assert "<p>" not in item.full_text
    assert item.language == "el"
    # KAD 46.35 in the body → deterministic Class A + a draft interpretation.
    assert item.content_class is ContentClass.A
    assert item.class_reasoning.rule_id == "kad_direct_mention"
    assert item.interpretation is not None


def test_eurlex_rerun_is_idempotent(runner, gateway):
    cfg = SourceConfig(name="EUR-Lex", tier=1,
                       endpoint="http://publications.europa.eu/webapi/rdf/sparql",
                       cadence="30m", authority_rank=1, adapter="eurlex",
                       options={"resource_types": ["REG"]})

    def make():
        return EurLexAdapter(cfg, HttpClient(_transport, sleep=lambda s: None),
                             now=date(2026, 7, 13))

    runner.run(make())
    runner.run(make())
    assert gateway.count() == 1  # upsert-by-key holds (AD-4, AD-14)
