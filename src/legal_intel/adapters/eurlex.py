"""EUR-Lex / CELLAR adapter (Story 1.2, FR-1).

Queries the CELLAR SPARQL endpoint for EU Regulations/Directives/CJEU case-law
published within a config lookback window, pre-filtered by EuroVoc descriptors,
then fetches each work's HTML body for extraction downstream. Emits one
SourceRecord per CELEX. A corrigendum (CELEX with an ``R(nn)`` suffix) is a
distinct Legal Event carrying a raw ``supersedes_ref`` for dedup to link (AD-15).

All endpoints, resource types, EuroVoc descriptors, and the lookback window come
from ``sources.yaml`` options (AD-8). HTTP goes through the injected client so
tests run offline against fixtures.
"""
from __future__ import annotations

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

_RESOURCE_TYPE_BASE = "http://publications.europa.eu/resource/authority/resource-type/"
_CELEX_REST = "http://publications.europa.eu/resource/celex/"
_SPARQL_JSON = "application/sparql-results+json"

# A corrigendum/consolidated suffix, e.g. 32024R1679R(01) -> base 32024R1679.
_CORRIGENDUM = re.compile(r"^(?P<base>.+?)R\(\d+\)$")


class EurLexAdapter(SourceAdapter):
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

    # -- query construction (config-driven) -------------------------------- #
    def _from_date(self) -> date:
        lookback = int(self.cfg.options.get("lookback_days", 7))
        return self._now - timedelta(days=lookback)

    def build_query(self) -> str:
        opts = self.cfg.options
        resource_types = opts.get("resource_types", ["REG", "DIR"])
        type_uris = ",\n        ".join(
            f"<{_RESOURCE_TYPE_BASE}{t}>" for t in resource_types
        )
        language = opts.get("language", "ENG")
        limit = int(opts.get("limit", 100))
        eurovoc = opts.get("eurovoc_descriptors", [])

        eurovoc_clause = ""
        if eurovoc:
            values = " ".join(f'"{d}"' for d in eurovoc)
            eurovoc_clause = (
                "  ?work cdm:work_is_about_concept_eurovoc ?ev .\n"
                "  ?ev skos:prefLabel ?evLabel .\n"
                f"  VALUES ?evLabel {{ {values} }}\n"
            )

        return f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?work ?celex ?title ?date ?type WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_date_document ?date .
  ?work cdm:work_has_resource-type ?resType .
  ?resType skos:prefLabel ?type .
  ?exp cdm:expression_belongs_to_work ?work .
  ?exp cdm:expression_title ?title .
  ?exp cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{language}> .
{eurovoc_clause}  FILTER(?date >= "{self._from_date().isoformat()}"^^xsd:date)
  FILTER(?resType IN (
        {type_uris}
  ))
}}
ORDER BY DESC(?date)
LIMIT {limit}"""

    # -- fetch ------------------------------------------------------------- #
    def fetch(self) -> Iterable[SourceRecord]:
        resp = self.http.get(
            self.cfg.endpoint,
            params={"query": self.build_query(), "format": _SPARQL_JSON},
            accept=_SPARQL_JSON,
        )
        bindings = json.loads(resp.text).get("results", {}).get("bindings", [])
        for b in bindings:
            record = self._to_record(b)
            if record is not None:
                yield record

    def _to_record(self, binding: dict) -> Optional[SourceRecord]:
        def val(key: str) -> str:
            return binding.get(key, {}).get("value", "")

        celex = val("celex")
        if not celex:
            return None

        raw_metadata: dict = {"celex": celex, "work_uri": val("work")}
        m = _CORRIGENDUM.match(celex)
        if m:
            raw_metadata["supersedes_ref"] = m.group("base")  # AD-15

        raw_body: Optional[bytes] = None
        content_type: Optional[str] = None
        try:
            body = self.http.get(
                f"{_CELEX_REST}{celex}",
                accept="text/html",
                headers={"Accept-Language": "el"},
            )
            raw_body = body.content
            content_type = body.content_type or "text/html"
        except Exception as exc:  # full text is best-effort; identity still emits
            self.log.log(source=self.name, event="fetch_fulltext",
                         status="degraded", error=str(exc), item_id=celex)

        return SourceRecord(
            source_id=celex,
            source_name=self.name,
            title=val("title") or celex,
            type=val("type") or "Regulation",
            authority="EU",
            date_published=parse_iso_date(val("date")),
            url=f"https://eur-lex.europa.eu/legal-content/EL/TXT/?uri=CELEX:{celex}",
            raw_body=raw_body,
            content_type=content_type,
            raw_metadata=raw_metadata,
        )
