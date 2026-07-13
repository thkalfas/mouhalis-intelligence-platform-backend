"""Story 1.4 — Βουλή, EDPB/EFSA (RSS), GDPRhub, data.gov.gr adapters (offline)."""
from __future__ import annotations

import json
from datetime import date

from legal_intel.adapters.datagovgr import DataGovGrAdapter
from legal_intel.adapters.gdprhub import GdprHubAdapter
from legal_intel.adapters.rss import RssAdapter
from legal_intel.adapters.vouli import VouliAdapter
from legal_intel.core.config import SourceConfig
from legal_intel.platform.http import HttpClient, HttpResponse


def _json_transport(payload):
    def _t(method, url, *, params=None, headers=None):
        body = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")
        return HttpResponse(200, url, body, {"content-type": "application/json"})
    return _t


def _client(transport):
    return HttpClient(transport, sleep=lambda s: None)


# --------------------------------------------------------------------------- #
# RSS (EDPB / EFSA)
# --------------------------------------------------------------------------- #
_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Guidelines 01/2026 on data transfers</title>
    <link>https://edpb.europa.eu/doc/guidelines-01-2026</link>
    <guid>edpb-guidelines-01-2026</guid>
    <pubDate>Mon, 06 Jul 2026 09:00:00 +0000</pubDate>
    <category>Guidelines</category>
    <description>Summary of the guidelines.</description>
  </item>
</channel></rss>"""


def test_rss_adapter_maps_edpb_item():
    def t(method, url, *, params=None, headers=None):
        return HttpResponse(200, url, _RSS.encode("utf-8"),
                            {"content-type": "application/rss+xml"})
    cfg = SourceConfig(name="EDPB", tier=1, endpoint="https://edpb/rss", cadence="daily@09:00",
                       authority_rank=1, options={"authority": "EDPB"})
    records = list(RssAdapter(cfg, _client(t)).fetch())
    assert len(records) == 1
    rec = records[0]
    assert rec.source_id == "edpb-guidelines-01-2026"
    assert rec.type == "Guidelines"
    assert rec.date_published == date(2026, 7, 6)
    assert rec.url.endswith("guidelines-01-2026")
    assert rec.full_text == "Summary of the guidelines."


# --------------------------------------------------------------------------- #
# Βουλή
# --------------------------------------------------------------------------- #
def test_vouli_adapter_defensive_key_mapping():
    payload = {"bills": [
        {"billId": "B-2026-42", "title": "Νομοσχέδιο για φορολογικά",
         "submissionDate": "2026-07-01"},
        {"code": "", "title": ""},  # incomplete → skipped
    ]}
    cfg = SourceConfig(name="Βουλή", tier=1, endpoint="https://hp/api.ashx",
                       cadence="daily@08:00", authority_rank=1, options={"period": 20})
    records = list(VouliAdapter(cfg, _client(_json_transport(payload))).fetch())
    assert len(records) == 1
    assert records[0].source_id == "B-2026-42"
    assert records[0].date_published == date(2026, 7, 1)
    assert records[0].authority == "Βουλή των Ελλήνων"


# --------------------------------------------------------------------------- #
# GDPRhub (MediaWiki: recentchanges + parse)
# --------------------------------------------------------------------------- #
def test_gdprhub_recentchanges_then_wikitext():
    def t(method, url, *, params=None, headers=None):
        if params and params.get("list") == "recentchanges":
            body = {"query": {"recentchanges": [
                {"title": "HDPA (Greece) - 45/2026", "timestamp": "2026-07-05T10:00:00Z"},
                {"title": "HDPA (Greece) - 45/2026", "timestamp": "2026-07-05T11:00:00Z"},  # dup
            ]}}
        else:
            body = {"parse": {"wikitext": {"*": "== Facts ==\nDecision text."}}}
        return HttpResponse(200, url, json.dumps(body).encode("utf-8"),
                            {"content-type": "application/json"})
    cfg = SourceConfig(name="GDPRhub", tier=1, endpoint="https://gdprhub.eu/api.php",
                       cadence="daily@10:00", authority_rank=2)
    records = list(GdprHubAdapter(cfg, _client(t)).fetch())
    assert len(records) == 1  # dedup by title within the run
    rec = records[0]
    assert rec.source_id == "HDPA (Greece) - 45/2026"
    assert rec.date_published == date(2026, 7, 5)
    assert rec.full_text == "== Facts ==\nDecision text."
    assert rec.url.endswith("HDPA_(Greece)_-_45/2026")


# --------------------------------------------------------------------------- #
# data.gov.gr (API key from secret store)
# --------------------------------------------------------------------------- #
def test_datagovgr_requires_api_key(monkeypatch):
    monkeypatch.delenv("DATA_GOV_GR_API_KEY", raising=False)
    cfg = SourceConfig(name="data.gov.gr", tier=1, endpoint="https://data.gov.gr/api/v1",
                       cadence="daily", authority_rank=3, options={"dataset": "x"})
    assert list(DataGovGrAdapter(cfg, _client(_json_transport([]))).fetch()) == []


def test_datagovgr_maps_rows_and_sends_token(monkeypatch):
    monkeypatch.setenv("DATA_GOV_GR_API_KEY", "secret-key")
    captured = {}

    def t(method, url, *, params=None, headers=None):
        captured["auth"] = (headers or {}).get("Authorization")
        rows = [{"id": "r1", "title": "Στατιστικά ελέγχων", "date": "2026-06-30"}]
        return HttpResponse(200, url, json.dumps(rows).encode("utf-8"),
                            {"content-type": "application/json"})
    cfg = SourceConfig(name="data.gov.gr", tier=1, endpoint="https://data.gov.gr/api/v1",
                       cadence="daily", authority_rank=3, options={"dataset": "inspections"})
    records = list(DataGovGrAdapter(cfg, _client(t)).fetch())
    assert captured["auth"] == "Token secret-key"
    assert len(records) == 1
    assert records[0].source_id == "r1"
    assert records[0].date_published == date(2026, 6, 30)
