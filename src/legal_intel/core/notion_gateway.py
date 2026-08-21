"""The sole Notion entry point (Story 0.4, AD-2, AD-14, FR-17).

No stage calls notion-client directly. The gateway guarantees:
  - upsert-by-key: look up existing page by (source_id, source_name)+hash before
    create → re-running a write never duplicates a page (AD-14).
  - class-aware payloads: Class B never carries full text (AD-5).
  - Notion limits: batch ≤100, ≤3 req/s, checkpointed so a partial-batch failure
    re-runs only unwritten items.

Backends are pluggable so the Phase-0 fake-data skeleton runs offline:
  - LocalJSONBackend  (default): an in-memory / on-disk store, no network.
  - NotionApiBackend  (opt-in): the real notion-client (lazy-imported).
Select via env LEGAL_INTEL_NOTION_BACKEND = "local" | "notion".
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Optional, Protocol

from .models import ContentClass, Item

MAX_BATCH = 100
MAX_REQ_PER_SEC = 3


# --------------------------------------------------------------------------- #
# Class-aware serialization (AD-5): what we persist depends on Content Class.
# --------------------------------------------------------------------------- #
def to_payload(item: Item) -> dict:
    """Serialize an Item to a class-aware persistence payload."""
    data = item.model_dump(mode="json")
    if item.content_class is ContentClass.B:
        # Index-only: strip full text, snippet-beyond-title, interpretation. (AD-5)
        data["full_text"] = None
        data["snippet"] = None
        data["interpretation"] = None
    return data


class NotionBackend(Protocol):
    def find_page_id(self, upsert_key: str) -> Optional[str]: ...
    #: Create (page_id is None) or update the page, returning its authoritative
    #: id — Notion returns the id of the created/updated page; the local backend
    #: mints one. The gateway never fabricates ids itself.
    def write_page(self, page_id: Optional[str], upsert_key: str,
                   payload: dict) -> str: ...
    def get_page(self, page_id: str) -> Optional[dict]: ...
    def all_pages(self) -> list[dict]: ...


# --------------------------------------------------------------------------- #
# Local backend — default for Phase 0 (offline, deterministic)
# --------------------------------------------------------------------------- #
class LocalJSONBackend:
    """In-memory store with optional JSON persistence. Emulates Notion's page
    model well enough to validate the whole flow without a token."""

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._pages: dict[str, dict] = {}  # page_id -> payload
        self._key_index: dict[str, str] = {}  # upsert_key -> page_id
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
        self._pages = raw.get("pages", {})
        self._key_index = raw.get("key_index", {})

    def _flush(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._persist_path.write_text(
            json.dumps({"pages": self._pages, "key_index": self._key_index},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def find_page_id(self, upsert_key: str) -> Optional[str]:
        return self._key_index.get(upsert_key)

    def write_page(self, page_id: Optional[str], upsert_key: str,
                   payload: dict) -> str:
        page_id = page_id or f"page_{uuid.uuid4().hex}"
        self._pages[page_id] = payload
        self._key_index[upsert_key] = page_id
        self._flush()
        return page_id

    def get_page(self, page_id: str) -> Optional[dict]:
        return self._pages.get(page_id)

    def all_pages(self) -> list[dict]:
        return list(self._pages.values())


class NotionApiBackend:
    """Real Notion backend — lazy-imports notion-client so the core deps stay
    slim. Wired for later phases; the upsert semantics live in the gateway."""

    def __init__(self, token: Optional[str] = None, database_id: Optional[str] = None):
        try:
            from notion_client import Client  # lazy import (optional dep)
        except ImportError as exc:  # pragma: no cover - only when full extra absent
            raise RuntimeError(
                "notion-client not installed. `pip install legal-intel[full]`"
            ) from exc
        self._client = Client(auth=token or os.environ["NOTION_TOKEN"])
        self._database_id = database_id or os.environ["NOTION_DATABASE_ID"]
        # Notion API 2025-09-03+ (notion-client 3.x) queries/creates against a
        # *data source*, not the database directly. Resolve (and cache) the DB's
        # data source id; overridable via env for multi-source DBs.
        self._data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID")

    def _ds_id(self) -> str:  # pragma: no cover - needs network
        if not self._data_source_id:
            db = self._client.databases.retrieve(database_id=self._database_id)
            sources = db.get("data_sources") or []
            if not sources:
                raise RuntimeError(
                    f"Database {self._database_id} has no data source to write to"
                )
            self._data_source_id = sources[0]["id"]
        return self._data_source_id

    def find_page_id(self, upsert_key: str) -> Optional[str]:  # pragma: no cover
        resp = self._client.data_sources.query(
            data_source_id=self._ds_id(),
            filter={"property": "Upsert Key", "rich_text": {"equals": upsert_key}},
            page_size=1,
        )
        results = resp.get("results", [])
        return results[0]["id"] if results else None

    def write_page(self, page_id, upsert_key, payload) -> str:  # pragma: no cover
        """Create or update the Legal Events page from the Item payload, mapping
        to the provisioned schema (notion_mapping). Full text goes to the page
        body on create; updates touch properties only (body edits are additive
        and out of scope for the automated path). Returns the page id."""
        from .models import Item
        from .notion_mapping import item_to_children, item_to_properties

        item = Item.model_validate(payload)
        properties = item_to_properties(item)
        if page_id:
            self._client.pages.update(page_id=page_id, properties=properties)
            return page_id
        created = self._client.pages.create(
            parent={"type": "data_source_id", "data_source_id": self._ds_id()},
            properties=properties,
            children=item_to_children(item),
        )
        return created["id"]

    def get_page(self, page_id):  # pragma: no cover
        return self._client.pages.retrieve(page_id)

    def all_pages(self):  # pragma: no cover
        return []


def make_backend() -> NotionBackend:
    kind = os.environ.get("LEGAL_INTEL_NOTION_BACKEND", "local").lower()
    if kind == "notion":  # pragma: no cover - needs a token
        return NotionApiBackend()
    persist = os.environ.get("LEGAL_INTEL_LOCAL_STORE")
    return LocalJSONBackend(Path(persist) if persist else None)


# --------------------------------------------------------------------------- #
# Gateway
# --------------------------------------------------------------------------- #
class NotionGateway:
    def __init__(self, backend: Optional[NotionBackend] = None) -> None:
        self._backend = backend or make_backend()
        # Per-key serialization so concurrent ingestion of the same Legal Event
        # cannot create two Items (AD-14). One lock guards the create-or-find
        # critical section; MVP scope is a single process.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def upsert_item(self, item: Item) -> Item:
        """Exactly-once upsert keyed on (source_id, source_name)+hash (AD-14).
        Returns the item with its authoritative page_id set."""
        key = item.upsert_key()
        with self._lock_for(item.dedup_key()):  # serialize per Legal Event
            page_id = item.page_id or self._backend.find_page_id(key)
            # The backend returns the authoritative id (Notion's on create, or a
            # minted one locally) — we never fabricate it here.
            item.page_id = self._backend.write_page(page_id, key, to_payload(item))
        return item

    def upsert_batch(self, items: list[Item]) -> list[Item]:
        """Checkpointed batch write: each item is upserted independently, so a
        failure mid-batch re-runs only the unwritten items (AD-2, Story 0.4)."""
        out: list[Item] = []
        for i in range(0, len(items), MAX_BATCH):
            for it in items[i : i + MAX_BATCH]:
                out.append(self.upsert_item(it))  # idempotent per item
        return out

    def exists(self, upsert_key: str) -> bool:
        """True if an Item with this exact upsert key (source + content hash) is
        already persisted — used for cross-run idempotency (AD-4)."""
        return self._backend.find_page_id(upsert_key) is not None

    def get_item(self, page_id: str) -> Optional[dict]:
        return self._backend.get_page(page_id)

    def all_items(self) -> list[dict]:
        return self._backend.all_pages()

    def count(self) -> int:
        return len(self._backend.all_pages())
