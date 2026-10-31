"""RASFF Window adapter (Story 3.3, FR-2).

RASFF is captured by a **config-selectable mechanism** (spec §5.2.5):
  - ``mechanism: public`` — the free public search API behind the RASFF Window
    Angular frontend (POST, JSON, no key needed);
  - ``mechanism: apitalks`` — a paid 3rd-party REST feed (JSON), fetched via the
    Tier-1 HttpClient (no scraping, low effort, vendor lock-in);
  - ``mechanism: scrape`` — polite Tier-2 scraping of the Angular RASFF Window
    (needs a JS-capable fetcher injected into the ScrapeClient in production).

Either way, product + hazard are parsed from each notification (high-priority
hazards for this client: pathogens, heavy metals, mycotoxins, allergens). The
choice is per-source config so switching vendors never touches code (AD-8).
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
from ..platform.scrape_client import ScrapeClient
from ._util import now_utc, parse_iso_date
from .tier2 import HtmlListScraper, detect_hazard


def _parse_rasff_date(value: str) -> Optional[date]:
    """Parse 'DD-MM-YYYY HH:MM:SS' from the RASFF public API."""
    if not value:
        return None
    try:
        parts = value.split(" ")[0].split("-")
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        return None


class RasffAdapter(HtmlListScraper):
    def __init__(self, cfg: SourceConfig, client: Optional[ScrapeClient] = None,
                 *, http: Optional[HttpClient] = None, **kw) -> None:
        super().__init__(cfg, client, **kw)
        self._http = http
        self.log = get_logger()

    def fetch(self) -> Iterable[SourceRecord]:
        mechanism = self.cfg.options.get("mechanism", "public")
        if mechanism == "scrape":
            yield from super().fetch()
        elif mechanism == "apitalks":
            yield from self._fetch_apitalks()
        else:
            yield from self._fetch_public()

    def _fetch_public(self) -> Iterable[SourceRecord]:
        http = self._http or HttpClient()
        endpoint = self.cfg.endpoint
        lookback = int(self.cfg.options.get("lookback_days", 7))
        items_per_page = int(self.cfg.options.get("items_per_page", 25))
        cutoff = now_utc().date() - timedelta(days=lookback)
        hazards = self.cfg.options.get("hazards", [])
        page = 1

        while True:
            resp = http.post_json(endpoint, {
                "parameters": {"pageNumber": page, "itemsPerPage": items_per_page},
            })
            payload = json.loads(resp.text)
            rows = payload.get("notifications", [])
            if not rows:
                break

            self.log.log(source=self.name, event="fetch", status="ok",
                         item_id=f"page-{page}", count=len(rows))

            exhausted = False
            for row in rows:
                ref = str(row.get("reference", ""))
                if not ref:
                    continue
                pub_date = _parse_rasff_date(row.get("ecValidationDate", ""))
                if pub_date and pub_date < cutoff:
                    exhausted = True
                    break

                subject = row.get("subject", ref)
                hz_text = subject
                risk = row.get("riskDecision", {})
                if isinstance(risk, dict):
                    hz_text += " " + risk.get("description", "")
                hz = detect_hazard(hz_text, hazards) or (
                    risk.get("description") if isinstance(risk, dict) else None)

                category = row.get("productCategory", {})
                cat_desc = category.get("description", "") if isinstance(category, dict) else ""
                classification = row.get("notificationClassification", {})
                class_desc = classification.get("description", "") if isinstance(classification, dict) else ""

                origins = row.get("originCountries", [])
                origin_names = [o.get("organizationName", "") for o in origins if isinstance(o, dict)]

                yield SourceRecord(
                    source_id=ref,
                    source_name=self.name,
                    title=str(subject).strip(),
                    type=self.cfg.options.get("default_type", "RASFF Notification"),
                    authority=self.cfg.options.get("authority", "RASFF"),
                    date_published=pub_date,
                    url=f"https://webgate.ec.europa.eu/rasff-window/screen/notification/{ref}",
                    language="en",
                    raw_metadata={
                        "notif_id": row.get("notifId"),
                        "product_category": cat_desc,
                        "classification": class_desc,
                        "risk": risk.get("description", "") if isinstance(risk, dict) else "",
                        "hazard": hz,
                        "origin_countries": origin_names,
                    },
                    collected_at=now_utc(),
                )

            if exhausted or page >= payload.get("totalPages", 1):
                break
            page += 1

    def _fetch_apitalks(self) -> Iterable[SourceRecord]:
        http = self._http or HttpClient()
        endpoint = self.cfg.options.get("apitalks_endpoint") or self.cfg.endpoint
        headers = {}
        if self.cfg.options.get("apitalks_key_header") and self.cfg.options.get("apitalks_key"):
            headers[self.cfg.options["apitalks_key_header"]] = self.cfg.options["apitalks_key"]
        resp = http.get(endpoint, accept="application/json", headers=headers or None)
        payload = json.loads(resp.text)
        rows = payload if isinstance(payload, list) else (
            payload.get("data") or payload.get("results") or [])
        hazards = self.cfg.options.get("hazards", [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref = str(row.get("reference") or row.get("id") or "")
            if not ref:
                continue
            subject = row.get("subject") or row.get("product") or ref
            hz = detect_hazard(f"{subject} {row.get('hazard', '')}", hazards) \
                or row.get("hazard")
            yield SourceRecord(
                source_id=ref,
                source_name=self.name,
                title=str(subject),
                type=self.cfg.options.get("default_type", "RASFF Notification"),
                authority=self.cfg.options.get("authority", "RASFF"),
                date_published=parse_iso_date(str(row.get("date", ""))),
                url=row.get("url") or f"https://webgate.ec.europa.eu/rasff-window/screen/notification/{ref}",
                language="en",
                raw_metadata={"product": subject, "hazard": hz, "raw": row},
                collected_at=now_utc(),
            )
