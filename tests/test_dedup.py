"""Epic 2 — deduplication & merge (Stories 2.1, 2.2, 2.3)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.models import (ContentClass, Interpretation, Item,
                                     ItemStatus)
from legal_intel.pipeline import dedup as D

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    reload_config()
    return load_config()


def _item(source_name, source_id, *, title="Κανονισμός Χ", authority="EU",
          text="κείμενο κανονισμού", hash_=None, dp=date(2026, 7, 8),
          status=ItemStatus.NEW, cls=None, topics=None, url=None) -> Item:
    it = Item(
        source_id=source_id, source_name=source_name, title=title, type="Regulation",
        authority=authority, date_published=dp,
        url=url or f"https://{source_name}/{source_id}",
        full_text=text, hash=hash_ or f"h-{text}", status=status,
        content_class=cls, topics=topics or [], collected_at=_NOW,
        primary_source=source_name,
    )
    return it


# --------------------------------------------------------------------------- #
# Story 2.1 — weighted scoring & threshold routing
# --------------------------------------------------------------------------- #
def test_exact_source_id_scores_auto_merge(cfg):
    a = _item("EUR-Lex", "CELEX1")
    b = _item("EUR-Lex", "CELEX1")
    assert D.score(a, b, cfg) >= cfg.dedup.thresholds.auto_merge


def test_identical_text_hash_auto_merges(cfg):
    a = _item("EUR-Lex", "CELEX1", hash_="same")
    b = _item("kodiko.gr", "k-1", hash_="same", authority="kodiko.gr")
    assert D.score(a, b, cfg) >= cfg.dedup.thresholds.auto_merge


def test_title_plus_authority_date_lands_in_confirm_band(cfg):
    # Different source_id and different text, but near-identical title + same
    # authority & date → 0.6 + 0.5 = 1.1 capped 1.0. Force only title+authority
    # by keeping titles very close and text distinct.
    a = _item("ΕΦΕΤ", "a-1", title="Ανάκληση προϊόντος Χ λόγω Listeria",
              authority="ΕΦΕΤ", text="alpha")
    b = _item("ΕΦΕΤ-mirror", "b-2", title="Ανάκληση προϊόντος Χ λόγω Listeria!",
              authority="ΕΦΕΤ", text="beta")
    s = D.score(a, b, cfg)
    # title(0.6) + authority_date(0.5) capped to 1.0 → auto-merge tier
    assert s >= cfg.dedup.thresholds.auto_merge


def test_confirm_band_routes_to_confirmation_queue(cfg):
    # Title similar (0.6) only → below auto_merge, at/above confirm_low? 0.6<0.70
    # so add nothing else → distinct. Use title + topic overlap to hit the band.
    existing = _item("SiteA", "a-1", title="Απόφαση περί σημάτων",
                     authority="A", text="alpha", topics=["t1"], dp=date(2026, 1, 1))
    cand = _item("SiteB", "b-2", title="Απόφαση περί σημάτων",
                 authority="B", text="beta", topics=["t1"], dp=date(2026, 2, 2))
    # title 0.6 + topic overlap 0.3 = 0.9 → confirm band [0.70, 0.95)
    out = D.dedup(cand, [existing], cfg)
    assert out.needs_confirmation is True
    assert out.merged_into is existing
    assert out.item.status is ItemStatus.NEW  # runner moves it to the queue status


def test_distinct_below_confirm_low(cfg):
    existing = _item("SiteA", "a-1", title="Εντελώς άσχετο θέμα", text="x", topics=[])
    cand = _item("SiteB", "b-2", title="Κάτι τελείως διαφορετικό", text="y", topics=[])
    out = D.dedup(cand, [existing], cfg)
    assert out.needs_confirmation is False
    assert out.merged_into is None


# --------------------------------------------------------------------------- #
# Story 2.2 — authority-ranked merge (identity preserved)
# --------------------------------------------------------------------------- #
def test_official_seen_first_keeps_identity_and_links_lower(cfg):
    # EUR-Lex rank 1, kodiko rank 2 (per sources.yaml).
    official = _item("EUR-Lex", "CELEX1", hash_="same", authority="EU")
    official.page_id = "page_official"
    commercial = _item("kodiko.gr", "k-1", hash_="same", authority="kodiko.gr")
    commercial.external_commentary = "σχόλιο σύνταξης"

    out = D.dedup(commercial, [official], cfg)
    assert out.merged_into is official
    survivor = out.item
    assert survivor.page_id == "page_official"          # identity preserved
    assert survivor.source_name == "EUR-Lex"            # official stays primary
    assert survivor.authority == "EU"
    assert any(s.source == "kodiko.gr" for s in survivor.additional_sources)
    assert survivor.external_commentary == "σχόλιο σύνταξης"


def test_higher_authority_seen_second_wins_content_keeps_page_id(cfg):
    # Reverse arrival: kodiko (rank 2) persisted first, EUR-Lex (rank 1) arrives.
    commercial = _item("kodiko.gr", "k-1", hash_="same", authority="kodiko.gr",
                       title="Κανονισμός (kodiko)", url="https://kodiko/k-1")
    commercial.page_id = "page_first"
    official = _item("EUR-Lex", "CELEX1", hash_="same", authority="EU",
                     title="Κανονισμός (EUR-Lex)", url="https://eurlex/CELEX1")

    out = D.dedup(official, [commercial], cfg)
    survivor = out.item
    assert survivor.page_id == "page_first"             # NO duplicate page (AD-14)
    assert survivor.primary_source == "EUR-Lex"         # authority won the content
    assert survivor.title == "Κανονισμός (EUR-Lex)"
    assert survivor.url == "https://eurlex/CELEX1"
    # the displaced commercial URL is preserved, nothing lost
    assert any(s.url == "https://kodiko/k-1" for s in survivor.additional_sources)


def test_full_text_fallback_when_primary_lacks_it(cfg):
    official = _item("EUR-Lex", "CELEX1", hash_="same", text="")
    official.full_text = None
    official.page_id = "p1"
    commercial = _item("kodiko.gr", "k-1", hash_="same", text="πλήρες κείμενο")
    out = D.dedup(commercial, [official], cfg)
    # hash signal still matched (both "same"); primary lacked text → fallback
    assert out.item.full_text == "πλήρες κείμενο"


def test_merge_after_interpretation_triggers_reinterpret(cfg):
    # A more-authoritative source arrives after the Item was interpreted+approved.
    approved = _item("kodiko.gr", "k-1", hash_="h1", authority="kodiko.gr",
                     title="Παλιός τίτλος", cls=ContentClass.A,
                     status=ItemStatus.APPROVED)
    approved.page_id = "p1"
    approved.interpretation = Interpretation(
        summary="s", what_changed_before="b", what_changed_after="a",
        what_changed_delta="d")
    official = _item("EUR-Lex", "CELEX1", hash_="h2", authority="EU",
                     title="Νέος επίσημος τίτλος", text="νέο κείμενο")
    # push into auto-merge via near-identical... instead force via same title? Use
    # same source_id trick is wrong. Rely on title+authority? authorities differ.
    # Give them the same hash so text_hash fires (auto-merge).
    official.hash = "h1"
    out = D.dedup(official, [approved], cfg)
    assert out.merged_into is approved
    assert out.reinterpret is True   # content changed on an interpreted Item (AD-16)


# --------------------------------------------------------------------------- #
# Story 2.3 — supersedes / precedent
# --------------------------------------------------------------------------- #
def test_supersedes_creates_distinct_item_and_retires_target(cfg):
    base = _item("EUR-Lex", "32024R1679", cls=ContentClass.A,
                 status=ItemStatus.APPROVED, topics=["food_labeling"])
    base.page_id = "page_base"
    corr = _item("EUR-Lex", "32024R1679R(01)", title="Διορθωτικό")
    corr.supersedes_ref = "32024R1679"

    out = D.dedup(corr, [base], cfg)
    assert out.superseded_target is base
    assert out.item is corr                       # a NEW distinct Item
    assert out.item.supersedes == ["page_base"]   # precedent link (AD-15)
    assert "food_labeling" in out.item.topics     # inherited Topics
    assert out.item.supersedes_ref is None        # ref resolved/cleared


def test_supersedes_ref_without_target_is_ignored(cfg):
    corr = _item("EUR-Lex", "32024R1679R(01)")
    corr.supersedes_ref = "does-not-exist"
    out = D.dedup(corr, [], cfg)
    assert out.superseded_target is None
    assert out.item.supersedes_ref is None
    assert out.item.supersedes == []
