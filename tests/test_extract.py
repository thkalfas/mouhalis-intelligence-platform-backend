"""Story 1.1 — text extraction & language detection."""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from legal_intel.pipeline.extract import detect_language, extract_text


# --------------------------------------------------------------------------- #
# HTML / plain text
# --------------------------------------------------------------------------- #
def test_html_extraction_strips_tags_and_scripts():
    html = (
        "<html><head><style>.x{color:red}</style>"
        "<script>var a=1;</script></head>"
        "<body><h1>Τίτλος</h1><p>Κείμενο νόμου.</p></body></html>"
    )
    result = extract_text(html, content_type="text/html")
    assert "Τίτλος" in result.text
    assert "Κείμενο νόμου." in result.text
    assert "color:red" not in result.text
    assert "var a=1" not in result.text
    assert result.needs_ocr is False


def test_html_sniffed_without_content_type():
    result = extract_text("<!DOCTYPE html><body><p>Hello</p></body>")
    assert result.text.strip() == "Hello"


def test_plain_text_passthrough():
    result = extract_text("  just plain text  ")
    assert result.text == "just plain text"
    assert result.needs_ocr is False


def test_bytes_utf8_decoded():
    result = extract_text("Κείμενο".encode("utf-8"), content_type="text/plain")
    assert result.text == "Κείμενο"


# --------------------------------------------------------------------------- #
# PDF (fake pdfplumber injected so the heavy dep is not required)
# --------------------------------------------------------------------------- #
@contextmanager
def _fake_pdfplumber(pages_text: list[str]):
    mod = types.ModuleType("pdfplumber")

    class _Page:
        def __init__(self, txt: str) -> None:
            self._txt = txt

        def extract_text(self) -> str:
            return self._txt

    class _PDF:
        def __init__(self) -> None:
            self.pages = [_Page(t) for t in pages_text]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    mod.open = lambda _stream: _PDF()  # type: ignore[attr-defined]
    sys.modules["pdfplumber"] = mod
    try:
        yield
    finally:
        del sys.modules["pdfplumber"]


def test_pdf_with_text_layer():
    body = b"%PDF-1.7 ...binary..."
    with _fake_pdfplumber(["Σελίδα 1 κειμένου", "Σελίδα 2"]):
        result = extract_text(body, content_type="application/pdf")
    assert "Σελίδα 1 κειμένου" in result.text
    assert "Σελίδα 2" in result.text
    assert result.needs_ocr is False


def test_scanned_pdf_flags_needs_ocr():
    body = b"%PDF-1.7 scanned image only"
    with _fake_pdfplumber(["", "  "]):  # no embedded text layer
        result = extract_text(body)  # sniffed by the %PDF- magic bytes
    assert result.text == ""
    assert result.needs_ocr is True


# --------------------------------------------------------------------------- #
# Language detection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Ο παρών κανονισμός θεσπίζει υποχρεώσεις", "el"),
        ("This Regulation lays down obligations", "en"),
        ("1234567890 %%% +++ === !!!", "other"),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_language_hint_wins():
    assert detect_language("mostly english words here", hint="el") == "el"
