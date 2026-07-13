"""Story 4.1 — commercial shared-inbox newsletter parser (offline)."""
from __future__ import annotations

import email
from datetime import date

from legal_intel.adapters.inbox import CommercialInboxAdapter
from legal_intel.adapters.registry import build_adapter
from legal_intel.core.config import SourceConfig
from legal_intel.core.models import ContentClass, Item
from legal_intel.pipeline import dedup as D
from legal_intel.pipeline.normalize import normalize
from legal_intel.platform.http import HttpClient, HttpResponse

_HTML_EMAIL = """From: news@taxheaven.gr
Subject: Εβδομαδιαία φορολογικά νέα
Date: Mon, 06 Jul 2026 08:00:00 +0000
Content-Type: text/html; charset=utf-8

<html><body>
<p>Σχόλιο σύνταξης: σημαντικές αλλαγές στον ΦΠΑ.</p>
<a href="https://taxheaven.gr/news/123">Νέα εγκύκλιος ΑΑΔΕ για ΦΠΑ</a>
<a href="https://taxheaven.gr/news/124">Δεύτερο άρθρο</a>
</body></html>
"""

_PLAIN_EMAIL = """From: alerts@qualex.gr
Subject: Qualex daily
Date: Tue, 07 Jul 2026 09:00:00 +0000
Content-Type: text/plain; charset=utf-8

Δείτε το άρθρο εδώ: https://qualex.gr/a/42
"""


class _FakeReader:
    def __init__(self, raw_messages):
        self._raw = raw_messages

    def fetch_messages(self):
        # Parse from bytes, like the production IMAP reader — message_from_string
        # mangles non-ASCII bodies (raw-unicode-escape).
        for raw in self._raw:
            yield email.message_from_bytes(raw.encode("utf-8"))


def _http(fail_urls=None):
    fail = fail_urls or set()

    def transport(method, url, *, params=None, headers=None):
        if url in fail:
            return HttpResponse(500, url, b"", {})
        return HttpResponse(200, url, f"<html><body>Περιεχόμενο {url}</body></html>".encode(),
                            {"content-type": "text/html; charset=utf-8"})
    return HttpClient(transport, sleep=lambda s: None, backoff=())


def _cfg(**opts):
    base = {"default_source_name": "Commercial Newsletter", "default_type": "Newsletter",
            "sender_source_map": {"taxheaven.gr": "taxheaven.gr", "qualex": "Qualex"},
            "inbox_address": "legal-intel@client.gr"}
    base.update(opts)
    return SourceConfig(name="Commercial Inbox", tier=3, endpoint="imap://x",
                        cadence="30m", authority_rank=3, adapter="inbox", options=base)


def test_html_newsletter_yields_commercial_records():
    adapter = CommercialInboxAdapter(_cfg(), _http(), reader=_FakeReader([_HTML_EMAIL]))
    records = list(adapter.fetch())
    assert len(records) == 2
    rec = records[0]
    assert rec.source_id == "https://taxheaven.gr/news/123"
    assert rec.source_name == "taxheaven.gr"          # mapped from sender
    assert rec.title == "Νέα εγκύκλιος ΑΑΔΕ για ΦΠΑ"
    assert rec.date_published == date(2026, 7, 6)
    assert rec.raw_metadata["commercial"] is True
    assert "Σχόλιο σύνταξης" in rec.raw_metadata["external_commentary"]
    assert rec.raw_body is not None                    # link content fetched


def test_plain_text_newsletter_extracts_bare_urls():
    adapter = CommercialInboxAdapter(_cfg(), _http(), reader=_FakeReader([_PLAIN_EMAIL]))
    records = list(adapter.fetch())
    assert len(records) == 1
    assert records[0].source_id == "https://qualex.gr/a/42"
    assert records[0].source_name == "Qualex"


def test_link_fetch_failure_is_degraded_not_fatal():
    adapter = CommercialInboxAdapter(
        _cfg(), _http(fail_urls={"https://taxheaven.gr/news/123"}),
        reader=_FakeReader([_HTML_EMAIL]))
    records = list(adapter.fetch())
    assert len(records) == 2
    assert records[0].raw_body is None                 # degraded, still emitted
    assert records[1].raw_body is not None


def test_refuses_without_shared_inbox_address():
    # No inbox_address configured and no injected reader → refuse to read anything.
    cfg = SourceConfig(name="Commercial Inbox", tier=3, endpoint="imap://x",
                       cadence="30m", authority_rank=3, adapter="inbox", options={})
    adapter = CommercialInboxAdapter(cfg, _http())
    assert list(adapter.fetch()) == []


def test_link_allowlist_filters_out_other_domains():
    adapter = CommercialInboxAdapter(
        _cfg(link_allow_domains=["taxheaven.gr"]), _http(),
        reader=_FakeReader([_HTML_EMAIL, _PLAIN_EMAIL]))
    records = list(adapter.fetch())
    # qualex link filtered out; only the two taxheaven links remain
    assert {r.source_name for r in records} == {"taxheaven.gr"}
    assert len(records) == 2


def test_commercial_never_wins_metadata_over_official():
    reload = __import__("legal_intel.core.config", fromlist=["reload_config"])
    reload.reload_config()
    cfg = reload.load_config()

    # An official EUR-Lex item already stored, and a commercial newsletter record
    # for the same Legal Event (same normalized text → text-hash auto-merge).
    official = Item(
        source_id="CELEX1", source_name="EUR-Lex", title="Επίσημος τίτλος",
        type="Regulation", authority="EU", date_published=date(2026, 7, 8),
        url="https://eur-lex/CELEX1", full_text="κοινό κείμενο", hash="H",
        content_class=ContentClass.A, primary_source="EUR-Lex", page_id="p_off",
    )
    commercial_item = normalize(_commercial_source_record())
    commercial_item.hash = "H"  # same normalized text as the official item

    out = D.dedup(commercial_item, [official], cfg)
    survivor = out.item
    assert survivor.page_id == "p_off"                 # official identity kept
    assert survivor.title == "Επίσημος τίτλος"          # official metadata wins
    assert survivor.authority == "EU"
    assert survivor.external_commentary                 # commercial editorial preserved


def _commercial_source_record():
    from legal_intel.core.models import SourceRecord
    return SourceRecord(
        source_id="https://taxheaven.gr/news/123", source_name="taxheaven.gr",
        title="Εμπορικός τίτλος", type="Newsletter", authority="taxheaven.gr",
        date_published=date(2026, 7, 6), url="https://taxheaven.gr/news/123",
        full_text="κοινό κείμενο",
        raw_metadata={"commercial": True, "external_commentary": "σχόλιο σύνταξης"},
    )


def test_registry_builds_inbox_adapter():
    cfg = _cfg()
    assert isinstance(build_adapter(cfg), CommercialInboxAdapter)
