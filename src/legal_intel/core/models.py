"""Domain models — the one typed contract every stage shares (Story 0.1).

Vocabulary is verbatim from the PRD Glossary; no synonyms elsewhere in code.
Field ownership follows the spine conventions:
  - ``confidence_score`` = triage-classifier value only
  - ``dedup_score``      = dedup aggregate only
  - ``interpretation_confidence`` = interpretation self-assessment only
  - ``class_reasoning``  = the {decided_by, detail, rule_id?} envelope (AD, M4 fix)
The Env-B data contract (AD-11) is the set of fields marked "Env-B contract" below.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class ContentClass(str, Enum):
    A = "A"  # Relevant — full record + interpretation
    B = "B"  # Index-only — metadata + URL
    C = "C"  # Ambiguous — transient full text, awaiting human decision


class ItemStatus(str, Enum):
    """The pipe of the pipes-and-filters paradigm. See core.state_machine for
    which transitions are pipeline-owned vs human-only (AD-6)."""

    NEW = "New"
    AWAITING_TRIAGE = "Awaiting Triage"
    AWAITING_DEDUP_CONFIRMATION = "Awaiting Dedup Confirmation"  # AD-5 (H2 fix)
    CLASS_A_AWAITING_INTERPRETATION = "Class A - Awaiting Interpretation"
    CLASS_A_DRAFT_INTERPRETATION = "Class A - Draft Interpretation"
    CLASS_B_INDEXED = "Class B - Indexed"
    CLASS_C_AWAITING_HUMAN_REVIEW = "Class C - Awaiting Human Review"
    APPROVED = "Class A - Approved"
    REJECTED = "Class A - Rejected"
    REQUIRES_ACTION = "Class A - Requires Action"
    ARCHIVED = "Archived"
    SUPERSEDED = "Superseded"  # AD-15


class DecidedBy(str, Enum):
    RULE = "rule"
    LLM = "llm"


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #
class ClassReasoning(BaseModel):
    """Single envelope both the deterministic-rule and LLM producers emit, so
    Env-B's Explain Classification agent sees one contract (spine convention)."""

    decided_by: DecidedBy
    detail: str  # human-readable, Greek in production
    rule_id: Optional[str] = None


class SourceLink(BaseModel):
    source: str
    url: str
    collected_at: datetime


#: Map the LLM's occasional localized/variant level words to the canonical enum.
#: Real models sometimes answer in Greek or add parentheticals ("χαμηλή (1-2 ώρες)")
#: even when the schema is English — coerce rather than fail the whole Item.
_LEVEL_WORDS = {
    "low": "low", "medium": "medium", "high": "high", "med": "medium",
    "χαμηλη": "low", "χαμηλο": "low", "μικρη": "low", "μικρο": "low",
    "μεσαια": "medium", "μετρια": "medium", "μεσαιο": "medium", "μετριο": "medium",
    "υψηλη": "high", "υψηλο": "high", "μεγαλη": "high", "μεγαλο": "high",
}


def _strip_accents(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _coerce_level(value: str, default: str) -> str:
    if not isinstance(value, str):
        return default
    token = _strip_accents(value.strip().lower()).split("(")[0].strip()
    token = token.split()[0] if token else token
    return _LEVEL_WORDS.get(token, default)


class ActionItem(BaseModel):
    action: str
    owner_role: str
    deadline: str  # ISO date | "ongoing" | "upon_next_review"
    priority: Literal["high", "medium", "low"] = "medium"
    estimated_effort: Literal["low", "medium", "high"] = "medium"

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v):
        return _coerce_level(v, "medium") if v is not None else "medium"

    @field_validator("estimated_effort", mode="before")
    @classmethod
    def _norm_effort(cls, v):
        return _coerce_level(v, "medium") if v is not None else "medium"


class Interpretation(BaseModel):
    """Structured first-pass legal analysis for a Class A Item (FR-10, AD-9).
    Validated against this schema before any persist — a failure fails the Item."""

    summary: str
    what_changed_before: str
    what_changed_after: str
    what_changed_delta: str
    business_lines_affected: list[str] = Field(default_factory=list)
    support_functions_affected: list[str] = Field(default_factory=list)
    operational_impact: str = ""
    compliance_new_obligations: list[str] = Field(default_factory=list)
    compliance_lifted_obligations: list[str] = Field(default_factory=list)
    actions_required: list[ActionItem] = Field(default_factory=list)
    entry_into_force: Optional[str] = None
    transition_end: Optional[str] = None
    cited_articles: list[str] = Field(default_factory=list)
    confidence_notes: str = ""
    requires_specialist_review: bool = False
    specialist_domain: Optional[str] = None
    disclaimer: str = (
        "Η ερμηνεία παράγεται αυτόματα και υπόκειται σε νομική επικύρωση. "
        "Δεν αποτελεί νομική συμβουλή."
    )


# --------------------------------------------------------------------------- #
# SourceRecord — one raw capture, pre-dedup (AD-3)
# --------------------------------------------------------------------------- #
class SourceRecord(BaseModel):
    source_id: str
    source_name: str
    title: str
    type: str
    authority: str
    date_published: Optional[date] = None
    date_effective: Optional[date] = None
    url: str
    full_text: Optional[str] = None
    #: Raw body when text is not already plain (PDF/HTML), extracted by
    #: ``pipeline.normalize`` so extraction stays a single filter (FR-4). Adapters
    #: — the only code that talks to the outside world — download it; they never
    #: extract. Pre-normalization only; never persisted.
    raw_body: Optional[bytes] = None
    content_type: Optional[str] = None
    language: Optional[str] = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def dedup_key(self) -> str:
        """Cross-source identity component of the upsert key (AD-14)."""
        return f"{self.source_name}::{self.source_id}"


# --------------------------------------------------------------------------- #
# Item — the normalized, deduplicated record (the Notion page)
# --------------------------------------------------------------------------- #
class Item(BaseModel):
    # Group 1 — always populated (A, B, C)
    source_id: str
    source_name: str
    title: str
    type: str
    authority: str
    jurisdiction: Optional[str] = None
    date_published: Optional[date] = None
    date_effective: Optional[date] = None
    topics: list[str] = Field(default_factory=list)
    content_class: Optional[ContentClass] = None
    class_reasoning: Optional[ClassReasoning] = None  # Env-B contract (AD-11)
    confidence_score: Optional[float] = None  # triage classifier only
    dedup_score: Optional[float] = None  # dedup only
    # Triage classifier structured signals (Story 6.2). Populated only by the LLM
    # classifier path; used by review SLAs (action_signal) and routing.
    sector_touchpoints: list[str] = Field(default_factory=list)
    action_signal: Optional[str] = None  # immediate | monitor | none
    specialist_needed: Optional[bool] = None
    url: str = ""
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Optional[datetime] = None

    # Group 2 — full text (A + C only; never persisted for B, AD-5)
    full_text: Optional[str] = None
    language: Optional[str] = None
    snippet: Optional[str] = None
    hash: Optional[str] = None
    #: A scanned PDF with no text layer was detected; text extraction produced
    #: nothing and the item is flagged for OCR (future work) rather than silently
    #: persisted as empty (Story 1.1).
    needs_ocr: bool = False

    # Group 3 — interpretation (A only)
    interpretation: Optional[Interpretation] = None
    interpretation_confidence: Optional[float] = None  # interpret only

    # Env-B contract fields (AD-11)
    additional_sources: list[SourceLink] = Field(default_factory=list)
    external_commentary: Optional[str] = None
    supersedes: list[str] = Field(default_factory=list)  # Item ids (AD-15)

    #: The source_name whose metadata/full text currently populate the content
    #: fields — the most authoritative contributor seen so far. Identity
    #: (source_id/source_name/hash) stays first-seen for a stable upsert key
    #: (AD-14); authority governs *content* via this field (dedup merge, AD-15/2.2).
    primary_source: Optional[str] = None
    #: Transient raw pointer set by normalization from a source's
    #: `supersedes_ref` (e.g. a corrigendum's base CELEX). Dedup resolves it to a
    #: superseded Item id and clears it (AD-15). Not a persisted relation itself.
    supersedes_ref: Optional[str] = None
    #: Transient source-provided topic signals (EuroVoc descriptors, source topic
    #: hints) that the tagger maps to Ontology Topics (Story 5.1). Not persisted.
    descriptor_hints: list[str] = Field(default_factory=list)

    # Group 4 — human review workflow (Epic 8, spec §10.1). Populated by WF1/2/3.
    reviewer: Optional[str] = None
    review_started_at: Optional[datetime] = None
    review_completed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    review_feedback: dict[str, Any] = Field(default_factory=dict)  # edit diff (WF2)
    client_action_status: Optional[str] = None
    action_owner: Optional[str] = None
    action_deadline: Optional[date] = None
    reclassify_requested: bool = False
    reclassified_from_b: bool = False  # set on a B→A re-fetch (for the <5% metric)
    # Metric timestamps (spec §9.5).
    class_c_assigned_at: Optional[datetime] = None
    class_c_decided_at: Optional[datetime] = None
    draft_created_at: Optional[datetime] = None

    # Lifecycle
    status: ItemStatus = ItemStatus.NEW
    overdue: bool = False

    # Notion page id, assigned by the gateway on first upsert (authoritative id)
    page_id: Optional[str] = None

    def dedup_key(self) -> str:
        """The `(source_id, source_name)` half of the upsert key (AD-14)."""
        return f"{self.source_name}::{self.source_id}"

    def upsert_key(self) -> str:
        """`(source_id, source_name)` + content hash — the exactly-once key (AD-14)."""
        return f"{self.dedup_key()}::{self.hash or ''}"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Whitespace/punctuation normalization used before hashing (spec §3.3)."""
    lowered = text.lower()
    stripped = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", stripped).strip()


def text_hash(text: str) -> str:
    """SHA-256 of normalized full text (AD-4 idempotency key component)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
