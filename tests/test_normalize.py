"""Story 1.1 — normalization filter: extraction wiring, gate, hashing."""
from __future__ import annotations

from datetime import date

import pytest

from legal_intel.core.errors import PermanentError
from legal_intel.core.models import SourceRecord, text_hash
from legal_intel.pipeline.normalize import normalize


def _record(**overrides) -> SourceRecord:
    base = dict(
        source_id="CELEX:32026R0001",
        source_name="EUR-Lex",
        title="Κανονισμός δοκιμής",
        type="Regulation",
        authority="EU Commission",
        date_published=date(2026, 7, 8),
        url="https://eur-lex.europa.eu/x",
    )
    base.update(overrides)
    return SourceRecord(**base)


def test_extracts_html_raw_body_into_full_text():
    rec = _record(
        full_text=None,
        raw_body="<html><body><p>Ουσιαστικό κείμενο.</p></body></html>".encode("utf-8"),
        content_type="text/html",
    )
    item = normalize(rec)
    assert item.full_text == "Ουσιαστικό κείμενο."
    assert item.language == "el"
    assert item.snippet == "Ουσιαστικό κείμενο."
    assert item.hash == text_hash("Ουσιαστικό κείμενο.")
    assert item.needs_ocr is False


def test_plain_full_text_preferred_over_raw_body():
    rec = _record(full_text="Already plain", raw_body=b"<html>ignored</html>")
    item = normalize(rec)
    assert item.full_text == "Already plain"


def test_data_quality_gate_rejects_missing_fields():
    with pytest.raises(PermanentError):
        normalize(_record(title=""))
    with pytest.raises(PermanentError):
        normalize(_record(date_published=None))
    with pytest.raises(PermanentError):
        normalize(_record(url=""))


def test_no_text_hashes_title_and_detects_language():
    rec = _record(full_text=None, raw_body=None, title="English only title")
    item = normalize(rec)
    assert item.full_text is None
    assert item.language == "en"
    assert item.hash == text_hash("English only title")


def test_external_commentary_preserved():
    rec = _record(raw_metadata={"external_commentary": "σχόλιο"}, full_text="κείμενο")
    item = normalize(rec)
    assert item.external_commentary == "σχόλιο"
