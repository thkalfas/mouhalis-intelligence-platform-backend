"""Δι@ύγεια adapter (Story 1.3, FR-1).

The most critical Greek source: it indirectly covers ΕπΑντ, ΑΑΔΕ, ΕΦΕΤ, ΑΠΔΠΧ
and every ministry. Queries the opendata search API per configured organization
UID over a date window, emits one SourceRecord per ΑΔΑ, and downloads the
decision PDF (``documentUrl``) into ``raw_body`` for extraction downstream. A
``documentChecksum`` mismatch is logged (integrity signal), never fatal.

Org UIDs and the date window come from ``sources.yaml`` options (AD-8). HTTP goes
through the injected client so tests run offline.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import now_utc, parse_iso_date

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")


def _parse_diavgeia_date(value) -> Optional[date]:
    """Δι@ύγεια dates vary by endpoint: luminapi returns 'DD/MM/YYYY HH:MM:SS',
    others epoch-millis or ISO. Handle all three."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    s = str(value).strip()
    if s.isdigit():
        return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).date()
    m = _DMY.match(s)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return parse_iso_date(s)


class DiavgeiaAdapter(SourceAdapter):
    tier = 1

    def __init__(
        self,
        cfg: SourceConfig,
        http: Optional[HttpClient] = None,
        *,
        now: Optional[date] = None,
    ) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self._now = now or now_utc().date()
        self.log = get_logger()

    def _from_date(self) -> date:
        return self._now - timedelta(days=int(self.cfg.options.get("lookback_days", 7)))

    def fetch(self) -> Iterable[SourceRecord]:
        org_uids = self.cfg.options.get("organization_uids", [])
        if not org_uids:
            self.log.log(source=self.name, event="fetch", status="degraded",
                         error="no organization_uids configured")
            return
        # The opendata search returns duplicate decisions (repeated ΑΔΑ); de-dup
        # within a fetch so the same page isn't re-processed/re-written.
        seen: set[str] = set()
        for uid in org_uids:
            for rec in self._fetch_org(str(uid)):
                if rec.source_id in seen:
                    continue
                seen.add(rec.source_id)
                yield rec

    def _fetch_org(self, uid: str) -> Iterable[SourceRecord]:
        # Filter by org via the Lucene `q` — the value MUST be quoted (a bare/
        # unquoted field is ignored) and an in-`q` issueDate range 400s, so we
        # pull newest-first and let the runner's lookback window bound age.
        resp = self.http.get(
            f"{self.cfg.endpoint}/search",
            params={
                "q": f'organizationUid:"{uid}"',
                "size": str(self.cfg.options.get("page_size", 100)),
                "sort": "recent",
            },
            accept="application/json",
        )
        payload = json.loads(resp.text)
        decisions = payload.get("decisions") or payload.get("results") or []
        for dec in decisions:
            record = self._to_record(dec)
            if record is not None:
                yield record

    def _to_record(self, dec: dict) -> Optional[SourceRecord]:
        ada = dec.get("ada") or dec.get("ADA")
        if not ada:
            return None
        doc_url = dec.get("documentUrl") or dec.get("url", "")
        raw_body: Optional[bytes] = None
        content_type: Optional[str] = None
        if doc_url:
            raw_body, content_type = self._fetch_document(ada, doc_url,
                                                          dec.get("documentChecksum"))

        org = dec.get("organization", {})
        dec_type = dec.get("decisionType", {})
        return SourceRecord(
            source_id=ada,
            source_name=self.name,
            title=dec.get("subject") or ada,
            type=(dec_type.get("label") if isinstance(dec_type, dict) else dec_type) or "Απόφαση",
            authority=(org.get("label") if isinstance(org, dict) else org) or "",
            date_published=_parse_diavgeia_date(dec.get("issueDate") or dec.get("submissionTimestamp")),
            url=doc_url or f"https://diavgeia.gov.gr/decision/view/{ada}",
            raw_body=raw_body,
            content_type=content_type,
            raw_metadata={"ada": ada, "raw": dec},
        )

    def _fetch_document(self, ada, url, checksum) -> tuple[Optional[bytes], Optional[str]]:
        try:
            resp = self.http.get(url, accept="application/pdf")
        except Exception as exc:  # PDF is best-effort; identity still emits
            self.log.log(source=self.name, event="fetch_document",
                         status="degraded", error=str(exc), item_id=ada)
            return None, None
        if checksum and _SHA256_HEX.match(str(checksum)):
            actual = hashlib.sha256(resp.content).hexdigest()
            if actual.lower() != str(checksum).lower():
                self.log.log(source=self.name, event="checksum",
                             status="mismatch", item_id=ada,
                             error=f"expected {checksum}, got {actual}")
        return resp.content, resp.content_type or "application/pdf"
