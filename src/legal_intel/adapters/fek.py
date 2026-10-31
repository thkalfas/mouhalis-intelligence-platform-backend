"""ΦΕΚ adapter — Official Gazette via the ET search API.

The National Printing House (search.et.gr) React frontend calls a public Azure
Functions API that returns structured JSON per publication date. This adapter
calls that API directly, bypassing the JS-rendered frontend.

API: POST https://searchetv99.azurewebsites.net/api/searchbydate
Body: {"datePublished": "YYYY-MM-DD"}
Response: {"status": "ok", "data": "<JSON array string>"}
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Optional

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import now_utc

_ISSUE_NAMES = {
    "1": "Α", "2": "Β", "3": "Γ", "4": "Δ",
    "5": "Ε", "14": "Υ.Ο.Δ.Δ.", "15": "Α.Σ.Ε.Π.",
}


def _parse_api_date(value: str) -> Optional[date]:
    """Parse 'MM/DD/YYYY HH:MM:SS' from the ET API."""
    if not value:
        return None
    try:
        parts = value.split(" ")[0].split("/")
        return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


class FekAdapter(SourceAdapter):
    tier = 1

    def __init__(self, cfg: SourceConfig, http: Optional[HttpClient] = None,
                 *, now: Optional[date] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self._now = now or now_utc().date()
        self.log = get_logger()

    def fetch(self) -> Iterable[SourceRecord]:
        lookback = int(self.cfg.options.get("lookback_days", 7))
        authority = self.cfg.options.get("authority", "Εθνικό Τυπογραφείο")
        default_type = self.cfg.options.get("default_type", "ΦΕΚ")

        for day_offset in range(lookback):
            query_date = self._now - timedelta(days=day_offset)
            yield from self._fetch_date(query_date, authority, default_type)

    def _fetch_date(self, query_date: date, authority: str,
                    default_type: str) -> Iterable[SourceRecord]:
        resp = self.http.post_json(
            self.cfg.endpoint,
            {"datePublished": query_date.isoformat()},
        )
        payload = json.loads(resp.text)
        if payload.get("status") != "ok":
            self.log.log(source=self.name, event="fetch", status="degraded",
                         error=payload.get("message", "unknown error"))
            return

        records = json.loads(payload.get("data", "[]"))
        self.log.log(source=self.name, event="fetch", status="ok",
                     item_id=query_date.isoformat(), count=len(records))

        for rec in records:
            issue_group = str(rec.get("search_IssueGroupID", ""))
            issue_name = _ISSUE_NAMES.get(issue_group, issue_group)
            label = rec.get("search_PrimaryLabel", "")
            fek_id = rec.get("search_ID", "")
            doc_num = rec.get("search_DocumentNumber", "")

            yield SourceRecord(
                source_id=f"fek-{fek_id}",
                source_name=self.name,
                title=label or f"ΦΕΚ {issue_name} {doc_num}",
                type=f"{default_type} {issue_name}" if issue_name else default_type,
                authority=authority,
                date_published=_parse_api_date(
                    rec.get("search_IssueDate", "")),
                url=f"https://search.et.gr/fek/?fekId={fek_id}",
                language="el",
                raw_metadata={
                    "fek_id": fek_id,
                    "document_number": doc_num,
                    "issue_group": issue_group,
                    "issue_name": issue_name,
                    "pages": rec.get("search_Pages", ""),
                    "publication_date": rec.get("search_PublicationDate", ""),
                },
                collected_at=now_utc(),
            )
