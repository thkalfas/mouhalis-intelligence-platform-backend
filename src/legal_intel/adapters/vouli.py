"""Βουλή των Ελλήνων adapter (Story 1.4, FR-1).

The parliamentary Open Data API is the best early-warning source — bills are
visible before they reach consultation or the ΦΕΚ. Queries the configured method
(default ``Bills``) for a legislative period and emits one SourceRecord per bill.
Full text is usually absent at this stage (early warning), so only identity +
metadata are captured; the ΦΕΚ scraper (Epic 3) picks up the enacted text.

Method, period, and the JSON key variants come from ``sources.yaml`` (AD-8).
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

# Defensive key lookup — the API's exact field names need live verification
# (spec §5.1.2), so we accept the common variants rather than hard-fail.
_ID_KEYS = ("id", "billId", "BillId", "code")
_TITLE_KEYS = ("title", "Title", "subject", "billTitle")
_DATE_KEYS = ("submissionDate", "SubmissionDate", "date", "voteDate")
_URL_KEYS = ("url", "link", "documentUrl", "pdfUrl")


def _first(d: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v)
    return ""


class VouliAdapter(SourceAdapter):
    tier = 1

    def __init__(self, cfg: SourceConfig, http: Optional[HttpClient] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self.log = get_logger()

    def fetch(self) -> Iterable[SourceRecord]:
        params = {"q": self.cfg.options.get("method", "Bills")}
        period = self.cfg.options.get("period")
        if period is not None:
            params["period"] = str(period)
        resp = self.http.get(self.cfg.endpoint, params=params, accept="application/json")
        payload = json.loads(resp.text)
        rows = payload if isinstance(payload, list) else (
            payload.get("bills") or payload.get("items") or payload.get("results") or []
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            bill_id = _first(row, _ID_KEYS)
            title = _first(row, _TITLE_KEYS)
            if not bill_id or not title:
                continue
            yield SourceRecord(
                source_id=bill_id,
                source_name=self.name,
                title=title,
                type=self.cfg.options.get("default_type", "Νομοσχέδιο"),
                authority="Βουλή των Ελλήνων",
                date_published=parse_iso_date(_first(row, _DATE_KEYS)),
                url=_first(row, _URL_KEYS) or f"{self.cfg.endpoint}?q=Bills#{bill_id}",
                raw_metadata={"bill": row},
            )
