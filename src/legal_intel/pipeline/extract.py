"""Text extraction & language detection (Story 1.1, FR-4).

The single place raw source bodies (PDF / HTML / plain) become plain text, so
every adapter yields the same clean shape downstream regardless of source. Heavy
dependencies (pdfplumber) are lazy-imported here and only when a PDF is actually
seen — the offline walking skeleton and its tests never import them.

A scanned PDF (no embedded text layer) yields empty text and the ``needs_ocr``
flag, so the item is *flagged* rather than silently persisted as empty (AC 1.1).
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional, Union

Body = Union[bytes, str]


@dataclass
class ExtractResult:
    text: str
    needs_ocr: bool = False


# --------------------------------------------------------------------------- #
# HTML → text (stdlib only; no bs4 dependency for this)
# --------------------------------------------------------------------------- #
_SKIP_TAGS = {"script", "style", "head", "noscript"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    @property
    def text(self) -> str:
        return "\n".join(self._chunks)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text


# --------------------------------------------------------------------------- #
# PDF → text (pdfplumber, lazy)
# --------------------------------------------------------------------------- #
def _pdf_to_text(body: bytes) -> ExtractResult:
    try:
        import pdfplumber  # lazy — only when a PDF is actually seen
    except ImportError as exc:  # pragma: no cover - env without the `full` extra
        raise RuntimeError(
            "pdfplumber is required to extract PDF text; install the 'full' extra"
        ) from exc

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text)
    text = "\n".join(parts).strip()
    # No embedded text layer → scanned PDF → flag for OCR (future work).
    return ExtractResult(text=text, needs_ocr=(text == ""))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _looks_like_pdf(body: bytes) -> bool:
    return body[:5] == b"%PDF-"


def _looks_like_html(sample: str) -> bool:
    head = sample.lstrip()[:512].lower()
    return "<html" in head or "<!doctype html" in head or "<body" in head


def extract_text(body: Body, content_type: Optional[str] = None) -> ExtractResult:
    """Return plain text (and an OCR-needed flag) from a raw source body.

    ``content_type`` is a hint; sniffing the bytes wins when it is absent or
    wrong (public sources mislabel content type more often than one would hope).
    """
    ctype = (content_type or "").lower()

    if isinstance(body, bytes):
        if "pdf" in ctype or _looks_like_pdf(body):
            return _pdf_to_text(body)
        # Decode text/HTML bytes; be forgiving about declared vs actual encoding.
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode("latin-1", errors="replace")
    else:
        text = body

    if "html" in ctype or _looks_like_html(text):
        return ExtractResult(text=_html_to_text(text))
    return ExtractResult(text=text.strip())


# --------------------------------------------------------------------------- #
# Language detection (el / en / other) — Story 1.1
# --------------------------------------------------------------------------- #
def detect_language(text: str, hint: Optional[str] = None) -> str:
    """Three-way detection over letter scripts. A trustworthy source-provided
    ``hint`` (el/en) wins; otherwise we count Greek vs Latin letters."""
    if hint in ("el", "en", "other"):
        return hint

    greek = latin = 0
    for ch in text:
        # Greek and Coptic + Greek Extended blocks.
        if ("Ͱ" <= ch <= "Ͽ") or ("ἀ" <= ch <= "῿"):
            greek += 1
        elif ("a" <= ch.lower() <= "z"):
            latin += 1

    total = greek + latin
    if total == 0:
        return "other"
    if greek / total >= 0.30:
        return "el"
    if latin / total >= 0.50:
        return "en"
    return "other"
