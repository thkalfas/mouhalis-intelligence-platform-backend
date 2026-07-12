"""Fake source adapter for the Phase-0 walking skeleton (Story 0.9).

Emits a fixed mix of Legal Events designed to exercise every Content Class:
  - one that hits a KAD include rule  -> should become Class A
  - one in an excluded sector          -> should become Class B
  - one genuinely ambiguous            -> should become Class C
Plus a duplicate of the Class A event from a lower-authority source, to exercise
deduplication and merge.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone

from ..core.models import SourceRecord
from .base import SourceAdapter

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


class FakeSourceAdapter(SourceAdapter):
    name = "FakeSource"
    tier = 1

    def fetch(self) -> Iterable[SourceRecord]:
        yield SourceRecord(
            source_id="CELEX:32026R0001",
            source_name="EUR-Lex",
            title="Κανονισμός για την ιχνηλασιμότητα καπνικών προϊόντων (ΚΑΔ 46.35)",
            type="Regulation",
            authority="EU Commission",
            date_published=date(2026, 7, 8),
            url="https://eur-lex.europa.eu/legal-content/EL/TXT/?uri=CELEX:32026R0001",
            full_text=(
                "Ο παρών κανονισμός θεσπίζει νέες υποχρεώσεις ιχνηλασιμότητας για "
                "τη χονδρική εμπορία προϊόντων καπνού (ΚΑΔ 46.35). Οι επιχειρήσεις "
                "οφείλουν να καταγράφουν κάθε μετακίνηση προϊόντος. " * 6
            ),
            language="el",
            raw_metadata={"celex": "32026R0001"},
            collected_at=_NOW,
        )
        # Lower-authority duplicate of the above (kodiko.gr) -> dedup should merge.
        yield SourceRecord(
            source_id="kodiko-2026-0001",
            source_name="kodiko.gr",
            title="Νέος κανονισμός ιχνηλασιμότητας καπνικών — ΚΑΔ 46.35",
            type="Regulation",
            authority="kodiko.gr",
            date_published=date(2026, 7, 8),
            url="https://www.kodiko.gr/nomothesia/document/2026R0001",
            full_text=(
                "Ο παρών κανονισμός θεσπίζει νέες υποχρεώσεις ιχνηλασιμότητας για "
                "τη χονδρική εμπορία προϊόντων καπνού (ΚΑΔ 46.35). Οι επιχειρήσεις "
                "οφείλουν να καταγράφουν κάθε μετακίνηση προϊόντος. " * 6
            ),
            language="el",
            raw_metadata={"external_commentary": "Σχόλιο σύνταξης: σημαντικό για χονδρεμπόρους."},
            collected_at=_NOW,
        )
        # Excluded sector -> Class B
        yield SourceRecord(
            source_id="ADA:MARITIME-77",
            source_name="Διαύγεια",
            title="Απόφαση για ναυτιλιακά θέματα λιμένων",
            type="Απόφαση",
            authority="Υπουργείο Ναυτιλίας",
            date_published=date(2026, 7, 9),
            url="https://diavgeia.gov.gr/decision/ADA-MARITIME-77",
            full_text="Ρυθμίσεις για ναυτιλιακές δραστηριότητες και λιμενικές υποδομές. " * 4,
            language="el",
            raw_metadata={"topics_hint": ["maritime"]},
            collected_at=_NOW,
        )
        # Ambiguous -> Class C
        yield SourceRecord(
            source_id="ADA:FOOD-AMBIG-12",
            source_name="Διαύγεια",
            title="Εγκύκλιος για επισήμανση ορισμένων προϊόντων",
            type="Εγκύκλιος",
            authority="ΑΑΔΕ",
            date_published=date(2026, 7, 9),
            url="https://diavgeia.gov.gr/decision/ADA-FOOD-AMBIG-12",
            full_text="Διευκρινίσεις σχετικά με την επισήμανση προϊόντων σε ορισμένες περιπτώσεις. " * 4,
            language="el",
            raw_metadata={},
            collected_at=_NOW,
        )
