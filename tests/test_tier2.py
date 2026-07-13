"""Epic 3 — Tier-2 base, breakage alerting, and the config-driven scrapers."""
from __future__ import annotations

from datetime import date

from legal_intel.adapters.epant import EpantScraper
from legal_intel.adapters.rasff import RasffAdapter
from legal_intel.adapters.registry import build_adapter
from legal_intel.adapters.tier2 import HtmlListScraper, extract_rows
from legal_intel.core.config import SourceConfig
from legal_intel.platform.alerting import get_alerter
from legal_intel.platform.http import HttpClient, HttpResponse
from legal_intel.platform.politeness import PolitenessPolicy
from legal_intel.platform.scrape_client import ScrapeClient, ScrapeResponse


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _scrape_client(html: str):
    def fetch(url, *, headers):
        if url.endswith("/robots.txt"):
            return ScrapeResponse(200, url, b"User-agent: *\nAllow: /", {})
        return ScrapeResponse(200, url, html.encode("utf-8"),
                              {"content-type": "text/html"})
    return ScrapeClient(fetch, policy=PolitenessPolicy(),
                        clock=lambda: 1000.0, sleep=lambda s: None,
                        jitter=lambda b: b, ua_picker=lambda: "TestUA")


# --------------------------------------------------------------------------- #
# RowExtractor
# --------------------------------------------------------------------------- #
def test_row_extractor_captures_text_and_links():
    html = ("<table><tr class='r'><td><a href='/d/1'>Alpha</a></td>"
            "<td>08/07/2026</td></tr>"
            "<tr class='r'><td><a href='/d/2'>Beta</a></td></tr></table>")
    rows = extract_rows(html, "tr", "r")
    assert len(rows) == 2
    assert rows[0].first_link == ("/d/1", "Alpha")
    assert "08/07/2026" in rows[0].text


# --------------------------------------------------------------------------- #
# Story 3.3 — ΕΦΕΤ recalls with product + hazard
# --------------------------------------------------------------------------- #
_EFET_HTML = (
    "<html><body>"
    "<div class='item'><a href='/recall/123'>Ανάκληση τυριού λόγω Listeria</a>"
    "<span>08/07/2026</span></div>"
    "<div class='item'><a href='/recall/124'>Ανάκληση σοκολάτας - αλλεργιογόνο</a>"
    "<span>2026-07-09</span></div>"
    "</body></html>"
)


def _efet_cfg():
    return SourceConfig(
        name="ΕΦΕΤ", tier=2, endpoint="https://efet.gr/recalls", cadence="4h",
        authority_rank=1, adapter="efet",
        options={"row_tag": "div", "row_class": "item", "link_contains": "/recall/",
                 "default_type": "Ανάκληση", "authority": "ΕΦΕΤ",
                 "parse_hazard": True,
                 "hazards": [{"keyword": "listeria", "label": "Listeria"},
                             {"keyword": "αλλεργιογ", "label": "Αλλεργιογόνο"}]},
    )


def test_efet_parses_recalls_with_hazard():
    scraper = HtmlListScraper(_efet_cfg(), _scrape_client(_EFET_HTML))
    records = list(scraper.fetch())
    assert len(records) == 2
    first = records[0]
    assert first.source_id == "123"
    assert first.date_published == date(2026, 7, 8)
    assert first.raw_metadata["hazard"] == "Listeria"
    assert first.raw_metadata["product"].startswith("Ανάκληση τυριού")
    assert records[1].raw_metadata["hazard"] == "Αλλεργιογόνο"
    assert records[1].date_published == date(2026, 7, 9)


# --------------------------------------------------------------------------- #
# Story 3.2 — zero rows → degraded run + alert
# --------------------------------------------------------------------------- #
def test_zero_rows_fires_breakage_alert():
    alerter = get_alerter()
    before = len(alerter.alerts)
    cfg = _efet_cfg()
    scraper = HtmlListScraper(cfg, _scrape_client("<html><body>no rows here</body></html>"))
    records = list(scraper.fetch())
    assert records == []
    new = alerter.alerts[before:]
    assert any("zero rows" in msg for _lvl, msg, _ctx in new)


def test_change_detection_skips_unchanged_listing():
    seen: set[str] = set()
    cfg = _efet_cfg()
    client = _scrape_client(_EFET_HTML)
    first = list(HtmlListScraper(cfg, client, seen_hashes=seen).fetch())
    assert len(first) == 2
    # same content hash already seen → second run yields nothing new
    second = list(HtmlListScraper(cfg, client, seen_hashes=seen).fetch())
    assert second == []


# --------------------------------------------------------------------------- #
# Story 3.3 — RASFF, both mechanisms
# --------------------------------------------------------------------------- #
def test_rasff_apitalks_mechanism():
    rows = [{"reference": "2026.1234", "subject": "Salmonella in poultry",
             "hazard": "pathogenic microorganisms", "date": "2026-07-05",
             "url": "https://rasff/2026.1234"}]

    def transport(method, url, *, params=None, headers=None):
        import json
        return HttpResponse(200, url, json.dumps(rows).encode("utf-8"),
                            {"content-type": "application/json"})

    cfg = SourceConfig(
        name="RASFF", tier=2, endpoint="https://rasff/api", cadence="4h",
        authority_rank=1, adapter="rasff",
        options={"mechanism": "apitalks", "apitalks_endpoint": "https://rasff/api",
                 "hazards": [{"keyword": "pathogenic", "label": "Pathogens"}]},
    )
    adapter = RasffAdapter(cfg, None, http=HttpClient(transport, sleep=lambda s: None))
    records = list(adapter.fetch())
    assert len(records) == 1
    assert records[0].source_id == "2026.1234"
    assert records[0].raw_metadata["hazard"] == "Pathogens"


def test_rasff_scrape_mechanism_uses_html_list():
    html = ("<html><body><div class='item'>"
            "<a href='/notification/2026.9'>Listeria in cheese</a>"
            "<span>2026-07-01</span></div></body></html>")
    cfg = SourceConfig(
        name="RASFF", tier=2, endpoint="https://rasff/list", cadence="4h",
        authority_rank=1, adapter="rasff",
        options={"mechanism": "scrape", "row_tag": "div", "row_class": "item",
                 "link_contains": "/notification/", "parse_hazard": True,
                 "hazards": [{"keyword": "listeria", "label": "Listeria"}]},
    )
    adapter = RasffAdapter(cfg, _scrape_client(html))
    records = list(adapter.fetch())
    assert len(records) == 1
    assert records[0].raw_metadata["hazard"] == "Listeria"


# --------------------------------------------------------------------------- #
# Registry — tier-2 keys resolve to scrapers
# --------------------------------------------------------------------------- #
def test_registry_builds_tier2_scrapers():
    fek = build_adapter(SourceConfig(name="ΦΕΚ", tier=2, endpoint="https://et.gr",
                                     cadence="12h", authority_rank=1, adapter="fek"))
    epant = build_adapter(SourceConfig(name="ΕπΑντ", tier=2, endpoint="https://epant.gr",
                                       cadence="weekly", authority_rank=1, adapter="epant"))
    rasff = build_adapter(SourceConfig(name="RASFF", tier=2, endpoint="https://rasff",
                                       cadence="4h", authority_rank=1, adapter="rasff"))
    assert isinstance(fek, HtmlListScraper)
    assert isinstance(epant, EpantScraper)
    assert isinstance(rasff, RasffAdapter)
    # tier-2 adapters are wired with a ScrapeClient (politeness-enforcing)
    assert isinstance(fek.client, ScrapeClient)
