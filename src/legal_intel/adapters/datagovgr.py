"""data.gov.gr adapter (Story 1.4, FR-1).

A secondary source — public-sector datasets used mainly for ESG/compliance
context enrichment. Requires a free API key, read from the secret store (an env
var named in config), never hard-coded. A missing key degrades this one source
without affecting the others (AD-12).

The dataset path, id/title/date field names, and the key env var come from
``sources.yaml`` (AD-8); datasets vary too much for a fixed schema, so mapping is
config-driven and defensive.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Optional

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import parse_iso_date


class DataGovGrAdapter(SourceAdapter):
    tier = 1

    def __init__(self, cfg: SourceConfig, http: Optional[HttpClient] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self.log = get_logger()

    def _api_key(self) -> Optional[str]:
        return os.environ.get(self.cfg.options.get("api_key_env", "DATA_GOV_GR_API_KEY"))

    def fetch(self) -> Iterable[SourceRecord]:
        key = self._api_key()
        if not key:
            self.log.log(source=self.name, event="fetch", status="degraded",
                         error="missing data.gov.gr API key in secret store")
            return
        dataset = self.cfg.options.get("dataset", "")
        resp = self.http.get(
            f"{self.cfg.endpoint.rstrip('/')}/{dataset}".rstrip("/"),
            headers={"Authorization": f"Token {key}"},
            accept="application/json",
        )
        rows = json.loads(resp.text)
        if isinstance(rows, dict):
            rows = rows.get("result") or rows.get("data") or []

        id_field = self.cfg.options.get("id_field", "id")
        title_field = self.cfg.options.get("title_field", "title")
        date_field = self.cfg.options.get("date_field", "date")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            rid = str(row.get(id_field) or f"{dataset}:{i}")
            yield SourceRecord(
                source_id=rid,
                source_name=self.name,
                title=str(row.get(title_field) or f"{dataset} record {rid}"),
                type=self.cfg.options.get("default_type", "Dataset"),
                authority=self.cfg.options.get("authority", "data.gov.gr"),
                date_published=parse_iso_date(str(row.get(date_field, ""))),
                url=f"https://data.gov.gr/datasets/{dataset}/",
                raw_metadata={"row": row, "dataset": dataset},
            )
