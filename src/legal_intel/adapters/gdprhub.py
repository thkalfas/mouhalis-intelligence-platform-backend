"""GDPRhub adapter (Story 1.4, FR-1).

GDPRhub is a MediaWiki wiki of DPA decisions with English summaries and
GDPR-article cross-references. We poll ``recentchanges`` for newly touched pages
in the decisions namespace, then fetch each page's wikitext as full text. One
SourceRecord per page, keyed on the page title.

Namespace and limits come from ``sources.yaml`` (AD-8). The per-page parse fetch
is best-effort — a failure degrades that one page, not the run (AD-12).
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Optional

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import parse_iso_date


class GdprHubAdapter(SourceAdapter):
    tier = 1

    def __init__(self, cfg: SourceConfig, http: Optional[HttpClient] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self.log = get_logger()

    def fetch(self) -> Iterable[SourceRecord]:
        namespace = str(self.cfg.options.get("namespace", 0))
        limit = str(self.cfg.options.get("limit", 50))
        resp = self.http.get(
            self.cfg.endpoint,
            params={"action": "query", "list": "recentchanges",
                    "rcnamespace": namespace, "rclimit": limit, "format": "json"},
            accept="application/json",
        )
        changes = json.loads(resp.text).get("query", {}).get("recentchanges", [])
        seen: set[str] = set()
        for ch in changes:
            title = ch.get("title")
            if not title or title in seen:
                continue
            seen.add(title)
            yield self._to_record(title, ch.get("timestamp"))

    def _to_record(self, title: str, timestamp: Optional[str]) -> SourceRecord:
        full_text = self._fetch_wikitext(title)
        page_url = self.cfg.options.get("page_base", "https://gdprhub.eu/index.php?title=")
        return SourceRecord(
            source_id=title,
            source_name=self.name,
            title=title,
            type=self.cfg.options.get("default_type", "DPA Decision"),
            authority=self.cfg.options.get("authority", "GDPRhub"),
            date_published=parse_iso_date(timestamp),
            url=f"{page_url}{title.replace(' ', '_')}",
            full_text=full_text,
            raw_metadata={"page": title},
        )

    def _fetch_wikitext(self, title: str) -> Optional[str]:
        try:
            resp = self.http.get(
                self.cfg.endpoint,
                params={"action": "parse", "page": title,
                        "prop": "wikitext", "format": "json"},
                accept="application/json",
            )
            data = json.loads(resp.text)
            return data.get("parse", {}).get("wikitext", {}).get("*") or None
        except Exception as exc:  # best-effort; identity still emits
            self.log.log(source=self.name, event="fetch_wikitext",
                         status="degraded", error=str(exc), item_id=title)
            return None
