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
from datetime import date, timedelta
from typing import Optional

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import now_utc, parse_iso_date

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


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
        for uid in org_uids:
            yield from self._fetch_org(str(uid))

    def _fetch_org(self, uid: str) -> Iterable[SourceRecord]:
        resp = self.http.get(
            f"{self.cfg.endpoint}/search",
            params={
                "q": f"organizationUid:{uid}",
                "from_date": self._from_date().isoformat(),
                "size": str(self.cfg.options.get("page_size", 100)),
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
            date_published=parse_iso_date(dec.get("issueDate") or dec.get("submissionTimestamp")),
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
