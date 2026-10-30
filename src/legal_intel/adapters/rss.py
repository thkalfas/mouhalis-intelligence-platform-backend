"""Generic RSS/Atom adapter (Story 1.4, FR-1) — serves EDPB, EFSA, Βουλή.

Most sources publish RSS 2.0 feeds whose real content is a PDF behind the link;
we capture identity + the feed summary now (extraction of the linked PDF is a
later enrichment). One config-driven class covers all — the source name,
authority, feed URL, and default type all come from ``sources.yaml`` (AD-8).

Feeds without a ``<pubDate>`` (e.g. Βουλή) can specify a ``date_regex`` in
options to extract the date from the description/summary text, plus a
``date_format`` (strptime pattern, default ``%d/%m/%Y``).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Optional

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import parse_iso_date, parse_rfc822_date, parse_rss_items


class RssAdapter(SourceAdapter):
    tier = 1

    def __init__(self, cfg: SourceConfig, http: Optional[HttpClient] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self.log = get_logger()

    def _extract_date(self, pub_date_raw: Optional[str],
                      summary: Optional[str]):
        date_pub = parse_rfc822_date(pub_date_raw) or parse_iso_date(pub_date_raw)
        if date_pub is not None:
            return date_pub
        date_regex = self.cfg.options.get("date_regex")
        if date_regex and summary:
            m = re.search(date_regex, summary)
            if m:
                fmt = self.cfg.options.get("date_format", "%d/%m/%Y")
                try:
                    return datetime.strptime(m.group(1), fmt).date()
                except (ValueError, IndexError):
                    pass
        return None

    def fetch(self) -> Iterable[SourceRecord]:
        resp = self.http.get(self.cfg.endpoint, accept="application/rss+xml")
        try:
            items = parse_rss_items(resp.text)
        except Exception as exc:  # malformed feed → degraded, isolated (AD-12)
            self.log.log(source=self.name, event="parse_feed",
                         status="degraded", error=str(exc))
            return
        authority = self.cfg.options.get("authority", self.name)
        default_type = self.cfg.options.get("default_type", "Publication")
        for it in items:
            link = it.get("link", "")
            summary = it.get("summary") or None
            date_pub = self._extract_date(it.get("pubDate"), summary)
            yield SourceRecord(
                source_id=it.get("guid") or link,
                source_name=self.name,
                title=it.get("title", ""),
                type=it.get("category") or default_type,
                authority=authority,
                date_published=date_pub,
                url=link,
                full_text=summary,
                raw_metadata={"rss": it},
            )
