"""Adapter registry (Epic 1, Story 0.7 extension).

Maps the ``adapter`` key in each ``sources.yaml`` entry to its adapter class, so
the scheduler/CLI can instantiate exactly the enabled sources from config — new
sources are added by config + one adapter class, never by editing the runner
(AD-3, AD-8). Adapter modules are imported lazily so heavy backends stay out of
the offline path until a real source is actually built.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..core.config import AppConfig, SourceConfig
from ..platform.http import HttpClient
from .base import SourceAdapter

# adapter key -> "module:ClassName" (lazy import keeps httpx et al. off the
# offline path until a real source is instantiated).
_REGISTRY: dict[str, str] = {
    "fake": "legal_intel.adapters.fake:FakeSourceAdapter",
    "eurlex": "legal_intel.adapters.eurlex:EurLexAdapter",
    "diavgeia": "legal_intel.adapters.diavgeia:DiavgeiaAdapter",
    "rss": "legal_intel.adapters.rss:RssAdapter",
    "vouli": "legal_intel.adapters.vouli:VouliAdapter",
    "gdprhub": "legal_intel.adapters.gdprhub:GdprHubAdapter",
    "datagovgr": "legal_intel.adapters.datagovgr:DataGovGrAdapter",
}


def register(key: str, dotted: str) -> None:
    """Register an adapter key → 'module:Class' (used by tests / plugins)."""
    _REGISTRY[key] = dotted


def _resolve(dotted: str) -> type[SourceAdapter]:
    module_name, class_name = dotted.split(":", 1)
    import importlib

    return getattr(importlib.import_module(module_name), class_name)


def build_adapter(
    cfg: SourceConfig, http: Optional[HttpClient] = None
) -> SourceAdapter:
    """Instantiate the adapter for a source. ``fake`` needs no config/http; every
    real adapter takes ``(SourceConfig, http)``."""
    key = cfg.adapter
    if not key:
        raise ValueError(f"Source '{cfg.name}' has no adapter key configured")
    if key not in _REGISTRY:
        raise ValueError(f"Unknown adapter '{key}' for source '{cfg.name}'")
    cls = _resolve(_REGISTRY[key])
    if key == "fake":
        return cls()
    return cls(cfg, http)


def build_enabled_adapters(
    app_cfg: AppConfig, http: Optional[HttpClient] = None,
    http_factory: Optional[Callable[[], HttpClient]] = None,
) -> list[SourceAdapter]:
    """Instantiate every enabled source's adapter (scheduler/CLI entry point)."""
    adapters: list[SourceAdapter] = []
    for src in app_cfg.enabled_sources():
        client = http if http is not None else (http_factory() if http_factory else None)
        adapters.append(build_adapter(src, client))
    return adapters
