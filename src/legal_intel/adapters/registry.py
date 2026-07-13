"""Adapter registry (Epic 1/3, Story 0.7 extension).

Maps the ``adapter`` key in each ``sources.yaml`` entry to its adapter class, so
the scheduler/CLI can instantiate exactly the enabled sources from config — new
sources are added by config + one adapter class, never by editing the runner
(AD-3, AD-8). Adapter modules are imported lazily so heavy backends stay out of
the offline path until a real source is actually built.

Client wiring is tier-aware: Tier-1 adapters take an ``HttpClient``, Tier-2
scrapers take a politeness-enforcing ``ScrapeClient`` (AD-10). ``fake`` needs
neither.
"""
from __future__ import annotations

from typing import Optional, Union

from ..core.config import AppConfig, SourceConfig
from ..platform.http import HttpClient
from ..platform.scrape_client import ScrapeClient
from .base import SourceAdapter

# adapter key -> "module:ClassName" (lazy import keeps httpx/playwright et al. off
# the offline path until a real source is instantiated).
_REGISTRY: dict[str, str] = {
    "fake": "legal_intel.adapters.fake:FakeSourceAdapter",
    # Tier 1
    "eurlex": "legal_intel.adapters.eurlex:EurLexAdapter",
    "diavgeia": "legal_intel.adapters.diavgeia:DiavgeiaAdapter",
    "rss": "legal_intel.adapters.rss:RssAdapter",
    "vouli": "legal_intel.adapters.vouli:VouliAdapter",
    "gdprhub": "legal_intel.adapters.gdprhub:GdprHubAdapter",
    "datagovgr": "legal_intel.adapters.datagovgr:DataGovGrAdapter",
    # Tier 2
    "html_list": "legal_intel.adapters.tier2:HtmlListScraper",
    "fek": "legal_intel.adapters.tier2:HtmlListScraper",
    "ste": "legal_intel.adapters.tier2:HtmlListScraper",
    "efet": "legal_intel.adapters.tier2:HtmlListScraper",
    "dpa": "legal_intel.adapters.tier2:HtmlListScraper",
    "epant": "legal_intel.adapters.epant:EpantScraper",
    "rasff": "legal_intel.adapters.rasff:RasffAdapter",
}

Client = Union[HttpClient, ScrapeClient]


def register(key: str, dotted: str) -> None:
    """Register an adapter key → 'module:Class' (used by tests / plugins)."""
    _REGISTRY[key] = dotted


def _resolve(dotted: str) -> type[SourceAdapter]:
    module_name, class_name = dotted.split(":", 1)
    import importlib

    return getattr(importlib.import_module(module_name), class_name)


def _default_client(cfg: SourceConfig) -> Optional[Client]:
    if cfg.adapter == "fake":
        return None
    return ScrapeClient() if cfg.tier == 2 else HttpClient()


def build_adapter(cfg: SourceConfig, client: Optional[Client] = None) -> SourceAdapter:
    """Instantiate the adapter for a source. ``fake`` needs no config/client;
    every real adapter takes ``(SourceConfig, client)`` where the client type
    matches the tier."""
    key = cfg.adapter
    if not key:
        raise ValueError(f"Source '{cfg.name}' has no adapter key configured")
    if key not in _REGISTRY:
        raise ValueError(f"Unknown adapter '{key}' for source '{cfg.name}'")
    cls = _resolve(_REGISTRY[key])
    if key == "fake":
        return cls()
    return cls(cfg, client if client is not None else _default_client(cfg))


def build_enabled_adapters(app_cfg: AppConfig) -> list[SourceAdapter]:
    """Instantiate every enabled source's adapter (scheduler/CLI entry point),
    each with a tier-appropriate default client."""
    return [build_adapter(src) for src in app_cfg.enabled_sources()]
