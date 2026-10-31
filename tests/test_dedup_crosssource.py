"""Cross-source dedup proof (Pairs 1 & 2 from the source audit).

Validates that the same legal event arriving from different sources with
different source_ids, different source_names, and potentially different
authority spellings is correctly matched and merged — the core requirement
Antonis set before moving to Postgres/BYOC.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from legal_intel.core.config import load_config, reload_config
from legal_intel.core.models import Item, ItemStatus
from legal_intel.pipeline import dedup as D

_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    reload_config()
    return load_config()


def _item(source_name, source_id, *, title, authority, dp,
          text="", url=None, topics=None) -> Item:
    return Item(
        source_id=source_id, source_name=source_name, title=title,
        type="Απόφαση", authority=authority, date_published=dp,
        url=url or f"https://{source_name}/{source_id}",
        full_text=text, hash=f"h-{source_name}-{source_id}",
        status=ItemStatus.NEW, primary_source=source_name,
        topics=topics or [], collected_at=_NOW,
    )


# --------------------------------------------------------------------------- #
# Pair 1: ΕπΑντ decision — Διαύγεια API vs epant.gr scrape
# --------------------------------------------------------------------------- #
class TestPair1_EpantCrossSource:
    """An ΕπΑντ decision posted on Διαύγεια (ΑΔΑ as source_id, uppercase
    authority from the API) and listed on epant.gr (HTML-derived ID, mixed-case
    authority from config). Same title, same date, different IDs."""

    @pytest.fixture
    def diavgeia_record(self):
        return _item(
            source_name="Διαύγεια", source_id="9ΨΚΧ46ΜΤΛΠ-ΩΑΒ",
            title="Απόφαση ΕπΑντ αρ. 867/2026 - Συγκέντρωση επιχειρήσεων",
            authority="ΕΠΙΤΡΟΠΗ ΑΝΤΑΓΩΝΙΣΜΟΥ",
            dp=date(2026, 10, 15),
            url="https://diavgeia.gov.gr/decision/view/9ΨΚΧ46ΜΤΛΠ-ΩΑΒ",
        )

    @pytest.fixture
    def epant_record(self):
        return _item(
            source_name="ΕπΑντ", source_id="apofasi-867-2026",
            title="Απόφαση ΕπΑντ αρ. 867/2026 - Συγκέντρωση επιχειρήσεων",
            authority="Επιτροπή Ανταγωνισμού",
            dp=date(2026, 10, 15),
            url="https://epant.gr/apofaseis/apofasi-867-2026.html",
        )

    def test_authority_date_fires_despite_case_mismatch(self, cfg, diavgeia_record, epant_record):
        """The authority_date signal must fire even though the API returns
        uppercase and the config uses mixed case."""
        s = D.score(epant_record, diavgeia_record, cfg)
        assert s >= cfg.dedup.weights.authority_date

    def test_title_plus_authority_date_auto_merges(self, cfg, diavgeia_record, epant_record):
        """title_similarity (0.6) + authority_date (0.5) = 1.1 capped → auto-merge."""
        s = D.score(epant_record, diavgeia_record, cfg)
        assert s >= cfg.dedup.thresholds.auto_merge

    def test_dedup_merges_and_preserves_both_links(self, cfg, diavgeia_record, epant_record):
        diavgeia_record.page_id = "page_diavgeia"
        out = D.dedup(epant_record, [diavgeia_record], cfg)
        assert out.merged_into is diavgeia_record
        assert not out.needs_confirmation
        survivor = out.item
        assert survivor.page_id == "page_diavgeia"
        urls = {survivor.url} | {s.url for s in survivor.additional_sources}
        assert "https://epant.gr/apofaseis/apofasi-867-2026.html" in urls
        assert "https://diavgeia.gov.gr/decision/view/9ΨΚΧ46ΜΤΛΠ-ΩΑΒ" in urls

    def test_reverse_arrival_still_merges(self, cfg, diavgeia_record, epant_record):
        """Same result regardless of which source arrives first."""
        epant_record.page_id = "page_epant"
        out = D.dedup(diavgeia_record, [epant_record], cfg)
        assert out.merged_into is epant_record
        assert out.score >= cfg.dedup.thresholds.auto_merge


# --------------------------------------------------------------------------- #
# Pair 2: ΑΠΔΠΧ decision — Διαύγεια vs dpa.gr vs GDPRhub
# --------------------------------------------------------------------------- #
class TestPair2_APDPX_ThreeWay:
    """A Greek DPA decision with different authority names across sources:
    Διαύγεια returns the full official name, dpa.gr uses the abbreviation,
    GDPRhub is in English with a completely different title."""

    @pytest.fixture
    def diavgeia_record(self):
        return _item(
            source_name="Διαύγεια", source_id="Ψ2ΑΒ46ΜΤΛΠ-123",
            title="Επιβολή προστίμου σε εταιρεία για παραβίαση ΓΚΠΔ",
            authority="ΑΡΧΗ ΠΡΟΣΤΑΣΙΑΣ ΔΕΔΟΜΕΝΩΝ ΠΡΟΣΩΠΙΚΟΥ ΧΑΡΑΚΤΗΡΑ",
            dp=date(2026, 10, 20),
        )

    @pytest.fixture
    def dpa_record(self):
        return _item(
            source_name="dpa.gr", source_id="praksi-45-2026",
            title="Επιβολή προστίμου σε εταιρεία για παραβίαση ΓΚΠΔ",
            authority="ΑΠΔΠΧ",
            dp=date(2026, 10, 20),
        )

    @pytest.fixture
    def gdprhub_record(self):
        return _item(
            source_name="GDPRhub", source_id="HDPA_-_Decision_45/2026",
            title="HDPA - Decision 45/2026 - Fine imposed for GDPR violation",
            authority="HDPA",
            dp=date(2026, 10, 20),
        )

    def test_diavgeia_dpa_authority_alias_fires(self, cfg, diavgeia_record, dpa_record):
        """Full official name and abbreviation must resolve to the same canonical
        authority via the alias map."""
        s = D.score(dpa_record, diavgeia_record, cfg)
        assert s >= cfg.dedup.weights.authority_date

    def test_diavgeia_dpa_auto_merges(self, cfg, diavgeia_record, dpa_record):
        """Greek sources with identical title + aliased authority → auto-merge."""
        s = D.score(dpa_record, diavgeia_record, cfg)
        assert s >= cfg.dedup.thresholds.auto_merge

    def test_gdprhub_cross_language_lands_in_confirm_band(self, cfg, diavgeia_record, gdprhub_record):
        """English GDPRhub title vs Greek Διαύγεια title → title_similarity low.
        Different authority string ('HDPA' not aliased to ΑΠΔΠΧ). Should land
        below auto_merge — distinct or confirm band depending on other signals."""
        s = D.score(gdprhub_record, diavgeia_record, cfg)
        assert s < cfg.dedup.thresholds.auto_merge

    def test_three_way_merge_sequence(self, cfg, diavgeia_record, dpa_record, gdprhub_record):
        """Simulate all three arriving: A+B merge, C stays distinct or enters
        confirmation queue."""
        diavgeia_record.page_id = "page_dia"
        out1 = D.dedup(dpa_record, [diavgeia_record], cfg)
        assert out1.merged_into is diavgeia_record
        survivor = out1.item

        out2 = D.dedup(gdprhub_record, [survivor], cfg)
        assert out2.score < cfg.dedup.thresholds.auto_merge


# --------------------------------------------------------------------------- #
# Authority normalization edge cases
# --------------------------------------------------------------------------- #
class TestAuthorityNormalization:
    def test_casefold_matches_without_alias(self, cfg):
        """Pure case difference (no alias entry) still matches."""
        a = _item("A", "1", title="X", authority="EFSA", dp=date(2026, 1, 1))
        b = _item("B", "2", title="X", authority="efsa", dp=date(2026, 1, 1))
        s = D.score(a, b, cfg)
        assert s >= cfg.dedup.weights.authority_date

    def test_alias_resolves_abbreviation(self, cfg):
        a = _item("A", "1", title="X",
                  authority="ΕΝΙΑΙΟΣ ΦΟΡΕΑΣ ΕΛΕΓΧΟΥ ΤΡΟΦΙΜΩΝ", dp=date(2026, 1, 1))
        b = _item("B", "2", title="X", authority="ΕΦΕΤ", dp=date(2026, 1, 1))
        s = D.score(a, b, cfg)
        assert s >= cfg.dedup.weights.authority_date

    def test_empty_authority_never_matches(self, cfg):
        a = _item("A", "1", title="Unrelated title alpha", authority="", dp=date(2026, 1, 1))
        b = _item("B", "2", title="Unrelated title beta", authority="", dp=date(2026, 1, 1))
        s = D.score(a, b, cfg)
        assert s == 0.0
