"""Tier-2 scraping base: row extraction, change-detection, breakage alerts.

Story 3.2 (FR-2). All Tier-2 scrapers subclass ``Tier2Scraper`` and fetch only
through the injected ``ScrapeClient`` (Story 3.1) — there is no raw request path.
A listing that yields zero rows when content was expected is treated as a
*degraded* run and raises an ops alert (silent coverage loss is impossible), and
a content checksum lets an unchanged listing short-circuit without re-emitting.

``RowExtractor`` is a stdlib-only HTML row parser (no bs4 dependency), enough to
turn a listing table/list into (text, links) rows that concrete scrapers map to
SourceRecords. Real CSS selectors for each site must be verified against the live
page (spec §5.2) — the config drives which tag/class/regex to use.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.alerting import AlertLevel, get_alerter
from ..platform.logging import get_logger
from ..platform.scrape_client import ScrapeClient
from .base import SourceAdapter
from ._util import now_utc


# --------------------------------------------------------------------------- #
# Stdlib HTML row extractor
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, text)

    @property
    def first_link(self) -> Optional[tuple[str, str]]:
        return self.links[0] if self.links else None


class RowExtractor(HTMLParser):
    """Collect repeated rows (``row_tag`` with an optional class substring),
    capturing each row's visible text and anchor links. Handles nesting of the
    same tag."""

    def __init__(self, row_tag: str = "tr", row_class: Optional[str] = None) -> None:
        super().__init__(convert_charrefs=True)
        self._row_tag = row_tag.lower()
        self._row_class = row_class
        self.rows: list[Row] = []
        self._in_row = False
        self._depth = 0
        self._cur: Optional[Row] = None
        self._in_a = False
        self._a_href = ""
        self._a_text = ""

    def _class_matches(self, attrs: list[tuple[str, Optional[str]]]) -> bool:
        if not self._row_class:
            return True
        classes = dict(attrs).get("class") or ""
        return self._row_class in classes.split()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == self._row_tag:
            if self._in_row:
                self._depth += 1
            elif self._class_matches(attrs):
                self._in_row = True
                self._depth = 1
                self._cur = Row()
        if tag == "a" and self._in_row:
            self._in_a = True
            self._a_href = dict(attrs).get("href") or ""
            self._a_text = ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._in_a and self._cur is not None:
            self._cur.links.append((self._a_href, self._a_text.strip()))
            self._in_a = False
        if tag == self._row_tag and self._in_row:
            self._depth -= 1
            if self._depth == 0:
                self._cur.text = re.sub(r"\s+", " ", self._cur.text).strip()
                self.rows.append(self._cur)
                self._in_row = False
                self._cur = None

    def handle_data(self, data):
        if self._in_row and self._cur is not None:
            self._cur.text += data
            if self._in_a:
                self._a_text += data


def extract_rows(html: str, row_tag: str = "tr",
                 row_class: Optional[str] = None) -> list[Row]:
    parser = RowExtractor(row_tag, row_class)
    parser.feed(html)
    return parser.rows


# --------------------------------------------------------------------------- #
# Base scraper
# --------------------------------------------------------------------------- #
class Tier2Scraper(SourceAdapter):
    tier = 2

    def __init__(self, cfg: SourceConfig, client: Optional[ScrapeClient] = None,
                 *, seen_hashes: Optional[set[str]] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.client = client  # required for a real run; tests inject it
        self._seen = seen_hashes if seen_hashes is not None else set()
        self.log = get_logger()

    # Subclasses implement these two.
    def list_urls(self) -> list[str]:
        return list(self.cfg.options.get("list_urls") or [self.cfg.endpoint])

    def parse(self, html: str, url: str) -> list[SourceRecord]:  # pragma: no cover
        raise NotImplementedError

    def fetch(self) -> Iterable[SourceRecord]:
        if self.client is None:
            raise RuntimeError(f"{self.name}: no ScrapeClient configured")
        expect_nonempty = self.cfg.options.get("expect_nonempty", True)
        for url in self.list_urls():
            resp = self.client.get(url)
            content_hash = hashlib.sha256(resp.content).hexdigest()
            if content_hash in self._seen:
                self.log.log(source=self.name, event="scrape", status="unchanged",
                             item_id=url)
                continue
            self._seen.add(content_hash)
            records = self.parse(resp.text, url)
            if not records and expect_nonempty:
                # Zero rows where content was expected → selector breakage or an
                # empty page; a degraded run, never a silent empty-success (R1).
                self.log.log(source=self.name, event="scrape", status="degraded",
                             item_id=url, error="zero rows parsed")
                get_alerter().fire(
                    AlertLevel.WARNING,
                    f"Tier-2 scraper '{self.name}' returned zero rows — "
                    f"possible layout change", source=self.name, url=url,
                )
                continue
            self.log.log(source=self.name, event="scrape", status="ok",
                         item_id=url, count=len(records))
            yield from records


# --------------------------------------------------------------------------- #
# Hazard/product parsing (ΕΦΕΤ, RASFF) — config-driven keyword map
# --------------------------------------------------------------------------- #
def detect_hazard(text: str, hazards: list) -> Optional[str]:
    """Return a hazard label if any configured keyword appears in the text.
    ``hazards`` is a list of ``{keyword, label}`` (or bare keyword strings)."""
    low = text.lower()
    for h in hazards or []:
        if isinstance(h, dict):
            kw, label = h.get("keyword", ""), h.get("label", h.get("keyword", ""))
        else:
            kw, label = str(h), str(h)
        if kw and kw.lower() in low:
            return label
    return None


# --------------------------------------------------------------------------- #
# Generic config-driven HTML list scraper (ΦΕΚ, ΣτΕ, ΕΦΕΤ, dpa.gr, …)
# --------------------------------------------------------------------------- #
_DATE_PATTERNS = (
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), (1, 2, 3)),      # 2026-07-08
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), (3, 2, 1)),  # 08/07/2026
    (re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})"), (3, 2, 1)),  # 08-07-2026
)


def parse_any_date(text: str):
    from datetime import date
    for rx, (y, m, d) in _DATE_PATTERNS:
        mt = rx.search(text)
        if mt:
            try:
                return date(int(mt.group(y)), int(mt.group(m)), int(mt.group(d)))
            except ValueError:
                continue
    return None


class HtmlListScraper(Tier2Scraper):
    """A Tier-2 scraper whose behaviour is entirely config (AD-8): which row
    tag/class to read, how to pull id/date, the default type/authority, and
    optional product+hazard parsing. Concrete sources are config, not code."""

    def parse(self, html: str, url: str) -> list[SourceRecord]:
        o = self.cfg.options
        rows = extract_rows(html, o.get("row_tag", "tr"), o.get("row_class"))
        link_contains = o.get("link_contains")
        id_regex = re.compile(o["id_regex"]) if o.get("id_regex") else None
        hazards = o.get("hazards", [])
        parse_hazard = bool(o.get("parse_hazard"))
        authority = o.get("authority", self.name)
        default_type = o.get("default_type", "Απόφαση")

        records: list[SourceRecord] = []
        for row in rows:
            link = self._pick_link(row, link_contains)
            if link is None:
                continue
            href, title = link
            abs_url = urljoin(url, href)
            source_id = self._source_id(href, id_regex)
            raw_metadata: dict = {"row_text": row.text}
            if parse_hazard:
                hz = detect_hazard(f"{title} {row.text}", hazards)
                if hz:
                    raw_metadata["hazard"] = hz
                raw_metadata["product"] = title
            records.append(SourceRecord(
                source_id=source_id,
                source_name=self.name,
                title=title or row.text[:120],
                type=default_type,
                authority=authority,
                date_published=parse_any_date(row.text),
                url=abs_url,
                language="el",
                raw_metadata=raw_metadata,
                collected_at=now_utc(),
            ))
        return records

    @staticmethod
    def _pick_link(row: Row, link_contains: Optional[str]):
        for href, text in row.links:
            if not link_contains or link_contains in href:
                return href, text
        return None

    @staticmethod
    def _source_id(href: str, id_regex: Optional[re.Pattern]) -> str:
        if id_regex:
            m = id_regex.search(href)
            if m:
                return m.group(1) if m.groups() else m.group(0)
        return href.rstrip("/").rsplit("/", 1)[-1] or href
