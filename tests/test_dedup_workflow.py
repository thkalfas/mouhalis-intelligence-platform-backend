"""Epic 2 — dedup confirmation queue + supersession, end-to-end through the runner."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone

from legal_intel.adapters.base import SourceAdapter
from legal_intel.core.config import load_config, reload_config
from legal_intel.core.models import (ContentClass, Item, ItemStatus,
                                     SourceRecord)
from legal_intel.core.notion_gateway import LocalJSONBackend, NotionGateway
from legal_intel.pipeline import dedup as D

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Human confirmation resolution (HUMAN actor)
# --------------------------------------------------------------------------- #
def _queued_candidate() -> Item:
    return Item(
        source_id="b-2", source_name="SiteB", title="Απόφαση περί σημάτων",
        type="Απόφαση", authority="B", date_published=date(2026, 2, 2),
        url="https://siteb/b-2", full_text="beta", hash="hb",
        status=ItemStatus.AWAITING_DEDUP_CONFIRMATION, primary_source="SiteB",
        page_id="page_candidate",
    )


def _target() -> Item:
    return Item(
        source_id="a-1", source_name="SiteA", title="Απόφαση περί σημάτων",
        type="Απόφαση", authority="A", date_published=date(2026, 1, 1),
        url="https://sitea/a-1", full_text="alpha", hash="ha",
        status=ItemStatus.CLASS_B_INDEXED, content_class=ContentClass.B,
        primary_source="SiteA", page_id="page_target",
    )


def _gateway() -> NotionGateway:
    return NotionGateway(LocalJSONBackend())


def test_confirm_merge_archives_candidate_and_merges_into_target():
    reload_config()
    cfg = load_config()
    gw = _gateway()
    candidate, target = _queued_candidate(), _target()

    survivor = D.confirm_merge(candidate, target, cfg, gw)

    assert survivor.page_id == "page_target"
    assert candidate.status is ItemStatus.ARCHIVED
    # candidate URL preserved on the survivor; both pages persisted
    assert any(s.url == "https://siteb/b-2" for s in survivor.additional_sources)
    stored = {p["page_id"]: p for p in gw.all_items()}
    assert stored["page_candidate"]["status"] == ItemStatus.ARCHIVED.value


def test_reject_as_distinct_returns_item_to_triage():
    gw = _gateway()
    candidate = _queued_candidate()
    out = D.reject_as_distinct(candidate, gw)
    assert out.status is ItemStatus.AWAITING_TRIAGE
    stored = {p["page_id"]: p for p in gw.all_items()}
    assert stored["page_candidate"]["status"] == ItemStatus.AWAITING_TRIAGE.value


# --------------------------------------------------------------------------- #
# Runner-level: supersession retires the predecessor (AD-15)
# --------------------------------------------------------------------------- #
class _SupersedeAdapter(SourceAdapter):
    name = "EUR-Lex"
    tier = 1

    def fetch(self) -> Iterable[SourceRecord]:
        base_text = ("Κανονισμός για τη χονδρική εμπορία προϊόντων καπνού "
                     "ΚΑΔ 46.35 και υποχρεώσεις ιχνηλασιμότητας. " * 4)
        yield SourceRecord(
            source_id="32024R1679", source_name="EUR-Lex",
            title="Κανονισμός ιχνηλασιμότητας", type="Regulation", authority="EU",
            date_published=date(2026, 7, 8),
            url="https://eurlex/32024R1679", full_text=base_text,
            language="el", collected_at=_NOW,
        )
        yield SourceRecord(
            source_id="32024R1679R(01)", source_name="EUR-Lex",
            title="Διορθωτικό κανονισμού ιχνηλασιμότητας", type="Regulation",
            authority="EU", date_published=date(2026, 7, 10),
            url="https://eurlex/32024R1679R01",
            full_text=base_text + " Διόρθωση παραρτήματος.",
            language="el", raw_metadata={"supersedes_ref": "32024R1679"},
            collected_at=_NOW,
        )


def test_supersede_end_to_end_retires_predecessor(runner, gateway):
    runner.run(_SupersedeAdapter())
    items = {i.source_id: i for i in
             (Item.model_validate(p) for p in gateway.all_items())}

    base = items["32024R1679"]
    corr = items["32024R1679R(01)"]
    assert base.status is ItemStatus.SUPERSEDED            # predecessor retired
    assert corr.supersedes == [base.page_id]               # precedent link (AD-15)
    assert corr.content_class is ContentClass.A            # new version triaged fresh
    assert gateway.count() == 2                            # distinct Items, not merged


# --------------------------------------------------------------------------- #
# Probable duplicate lands in the confirmation queue (Story 2.3)
# --------------------------------------------------------------------------- #
def test_confirm_band_routes_second_item_to_queue():
    # Same title (0.6) + shared topic (0.3) = 0.9 → confirm band [0.70, 0.95).
    reload_config()
    cfg = load_config()
    existing = Item(
        source_id="a-1", source_name="ΕΦΕΤ", title="Ανάκληση προϊόντος Χ",
        type="Ανάκληση", authority="ΕΦΕΤ", date_published=date(2026, 3, 1),
        url="https://efet/a-1", full_text="alpha", hash="ha", topics=["t1"],
        content_class=ContentClass.A, status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION,
        primary_source="ΕΦΕΤ", page_id="p_exist",
    )
    cand = Item(
        source_id="b-2", source_name="taxheaven.gr", title="Ανάκληση προϊόντος Χ",
        type="Ανάκληση", authority="taxheaven", date_published=date(2026, 4, 2),
        url="https://taxheaven/b-2", full_text="beta", hash="hb", topics=["t1"],
        primary_source="taxheaven.gr",
    )
    out = D.dedup(cand, [existing], cfg)
    assert out.needs_confirmation is True
    assert out.merged_into is existing
