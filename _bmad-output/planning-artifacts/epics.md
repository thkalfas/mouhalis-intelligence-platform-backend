---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-mouhalis-legal-2026-07-13/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-mouhalis-legal-2026-07-13/ARCHITECTURE-SPINE.md
  - instructions.md
  - cowork-agents.md
project: mouhalis-legal
---

# Legal Intelligence Collection Layer — Epic Breakdown

## Overview

This document decomposes the PRD requirements (FR-1..FR-22) and the 16 architecture decisions (AD-1..AD-16) into implementable epics and stories for the Developer agent. Scope is **Environment A** (the Claude Code production pipeline), targeting **Path B (Notion-first)**. Epics are organized by user value and sequenced along the spec's phase plan (Phase 0 → Phase 3). Environment B (Cowork agents) is a separate downstream track and is not built here.

## Requirements Inventory

### Functional Requirements

- **FR-1** Tier-1 API ingestion · **FR-2** Tier-2 scraping with change-detection · **FR-3** Tier-3 commercial-inbox intake
- **FR-4** Normalization to unified schema · **FR-5** Weighted deduplication
- **FR-6** Ontology-based topic assignment
- **FR-7** Deterministic relevance rules · **FR-8** LLM relevance classifier · **FR-9** Class-aware retention
- **FR-10** Structured interpretation · **FR-11** Retrieval-augmented/few-shot interpretation · **FR-12** Model selection & escalation
- **FR-13** Class C relevance review (WF1) · **FR-14** Interpretation review (WF2) · **FR-15** Client-impact & action planning (WF3)
- **FR-16** Explicit state machine · **FR-17** Class-aware Notion sync · **FR-18** Bidirectional sync
- **FR-19** Scheduled orchestration · **FR-20** Monitoring/logging/alerting · **FR-21** Cost ledger & reporting
- **FR-22** Shared-state contract for Environment B

### NonFunctional Requirements

- Reliability (24/7, failure isolation, retry/backoff) · Scraping politeness & discretion · Observability (structured JSON logs, weekly report) · Data quality gates (<1% empty fields, >90% topic coverage) · Cost bounds ($15-30/mo MVP, per-item/monthly alerts) · GDPR self-compliance · Copyright/attribution/ToS.

### Additional Requirements

- **Architecture invariants (AD-1..AD-16)** — every story must comply; notably: pipes-and-filters over the Notion status blackboard (AD-1), Notion single System of Record with upsert-by-key (AD-2, AD-14), one SourceAdapter contract (AD-3), idempotency (AD-4), class-aware retention (AD-5), split transition ownership (AD-6), all-LLM-metered (AD-7), config-as-data (AD-8), interpretation validates before persist (AD-9), shared politeness middleware (AD-10), Env-B data contract (AD-11), failure isolation (AD-12), one consumer per status (AD-13), dedup-owned precedent (AD-15), late-merge re-interpretation (AD-16).

### UX Design Requirements

- No separate UX doc. The "UI" is the set of eight Notion views defined in PRD §10.2 / spec §10.2; view definitions are treated as UX requirements delivered in Epic 0 (schema/views) and Epic 8 (review workflows).

### FR Coverage Map

- FR-1 → Epic 1 (Tier-1 adapters)
- FR-2 → Epic 3 (Tier-2 scraping + politeness)
- FR-3 → Epic 4 (Tier-3 inbox); base SourceAdapter contract → Epic 0
- FR-4 → Epic 1 (normalization + extraction)
- FR-5 → Epic 2 (dedup, merge, dedup-confirmation queue)
- FR-6 → Epic 5 (topic tagging)
- FR-7 → Epic 6 (deterministic rules)
- FR-8 → Epic 6 (LLM classifier + triage agent)
- FR-9 → Epic 6 (class-aware retention)
- FR-10 → Epic 7 (structured interpretation)
- FR-11 → Epic 7 (RAG/few-shot)
- FR-12 → Epic 7 (model escalation)
- FR-13 → Epic 8 (WF1)
- FR-14 → Epic 8 (WF2)
- FR-15 → Epic 8 (WF3)
- FR-16 → Epic 0 (state machine)
- FR-17 → Epic 0 (class-aware Notion sync)
- FR-18 → Epic 8 (bidirectional edits, with review workflows)
- FR-19 → Epic 0 (scheduler skeleton) + each collection epic (register cadences)
- FR-20 → Epic 0 (logging/alerting) + each epic (emit)
- FR-21 → Epic 0 (cost ledger + MeteredLLMClient)
- FR-22 → Epic 0 (fields) + Epic 2 (precedent) + Epic 8 (re-fetch via reclassify)

## Epic List

### Epic 0: Walking Skeleton & Platform Foundation *(Phase 0 — the scaffold)*
Stand up the repository, the core contracts, the real Notion System of Record, and the platform (scheduler, cost ledger, logging, alerting), then prove an Item flows end-to-end (New → Awaiting Triage → Class A/B/C → Notion) using **fake** source adapters and stubbed triage/interpretation — with a green pytest. Validates the whole flow conceptually before investing in 10+ real connectors.
**FRs covered:** FR-16, FR-17, FR-19 (skeleton), FR-20, FR-21, FR-22 (fields); establishes the FR-3 SourceAdapter base contract.

### Epic 1: Tier-1 Collection — Official APIs
Replace fake adapters with real Tier-1 adapters (EUR-Lex/CELLAR, Δι@ύγεια, Βουλή, EDPB, EFSA, GDPRhub, data.gov.gr), including PDF/HTML text extraction and language detection, so real Legal Events flow into Notion.
**FRs covered:** FR-1, FR-4.

### Epic 2: Deduplication & Merge
Collapse multiple Source Records of the same Legal Event into one Item using weighted signals and the configured authority hierarchy; route probable duplicates to a human dedup-confirmation queue; own `supersedes`/precedent relations.
**FRs covered:** FR-5; realizes AD-14, AD-15, AD-16; contributes FR-22 (precedent).

### Epic 3: Tier-2 Collection — Scraping
Add the shared scraping-politeness middleware and Tier-2 scrapers (ΦΕΚ, ΣτΕ, ΕπΑντ, ΕΦΕΤ, RASFF, dpa.gr) with change-detection and breakage alerts, covering sources with no API.
**FRs covered:** FR-2.

### Epic 4: Tier-3 Collection — Commercial Inbox
Parse commercial newsletters from the dedicated shared inbox for cross-validation and safety-net coverage, tagged as commercial source.
**FRs covered:** FR-3.

### Epic 5: Topic Tagging
Tag each Item with Topics from the client-validated Ontology (rule-based first, LLM tagger for edge cases), driven entirely by config.
**FRs covered:** FR-6.

### Epic 6: Relevance Triage
Classify each tagged Item into Content Class A/B/C via deterministic rules then an LLM classifier, applying class-aware retention. Noise reduction is the core value.
**FRs covered:** FR-7, FR-8, FR-9.

### Epic 7: Interpretation Engine
Generate a structured, schema-validated draft legal Interpretation for each Class A Item via the 7-step pipeline, with retrieval augmentation, few-shot examples, and model escalation.
**FRs covered:** FR-10, FR-11, FR-12.

### Epic 8: Human Review Workflows & Feedback
Deliver the legal team's daily loop: the Class C relevance queue (WF1), interpretation review (WF2), client-impact/action planning (WF3), bidirectional Notion edits, the B→A reclassify re-fetch, and the weekly Quality Observer retro.
**FRs covered:** FR-13, FR-14, FR-15, FR-18; completes FR-22 (re-fetch entry point).

---

## Epic 0: Walking Skeleton & Platform Foundation

**Goal:** A runnable pipeline where a fake Legal Event travels the full state machine into a real Notion workspace, with cost/logging/alerting wired and a passing test suite — the conceptual proof before real connectors. Every later epic plugs real logic into these seams.

### Story 0.1: Project scaffold & core domain models

As a **developer**,
I want the repository, dependency setup, and the core pydantic domain models,
So that every later story builds on one typed contract for `SourceRecord`, `Item`, `Interpretation`, `ContentClass`, and `ItemStatus`.

**Acceptance Criteria:**

**Given** a fresh checkout
**When** I run the documented setup (`uv sync` / `pip install -e .`) on Python 3.12
**Then** the package `legal_intel` imports and `pytest` runs (even if only a placeholder test)
**And** the source tree matches the spine's Structural Seed (`core/`, `adapters/`, `pipeline/`, `agents/`, `platform/`, `config/`, `data/staging/`, `tests/`).

**Given** the domain models in `core/models.py`
**When** I construct an `Item`
**Then** it carries all mandatory fields (`source_id, source_name, title, type, authority, date_published, url, raw_metadata, collected_at, hash`) plus the Env-B contract fields (`class_reasoning` as the `{decided_by, detail, rule_id?}` envelope, `confidence_score`, `dedup_score`, `interpretation_confidence`, `additional_sources[]`, `external_commentary`, precedent relation ids) per AD-11
**And** `ContentClass` is an enum {A, B, C} and `ItemStatus` is an enum covering every status in the state machine including `Awaiting Dedup Confirmation` and `Superseded`.

### Story 0.2: State machine with split transition ownership

As a **developer**,
I want a single `core/state_machine.py` that defines every allowed status transition and who may perform it,
So that no stage can perform a human-only transition and illegal transitions are rejected (AD-6, AD-13).

**Acceptance Criteria:**

**Given** the state machine
**When** an automated stage requests a transition
**Then** only pipeline-owned transitions (New→Awaiting Triage→Class A/B/C→Draft Interpretation, and `Superseded`) are permitted
**And** human-only transitions (Approve, Reject, Requires Action, Reclassify, dedup-confirmation) raise a `PermanentError` if attempted by an automated caller.

**Given** any transition request
**When** the target is not defined as reachable from the current status
**Then** the request is rejected and structured-logged, never silently applied.

### Story 0.3: Config-as-data loader

As a **developer**,
I want `core/config.py` to load `config/*.yaml` once per run,
So that topics, rules, model IDs, cadences, and `authority_rank` come from config and never from code (AD-8).

**Acceptance Criteria:**

**Given** seed `config/sources.yaml`, `ontology.yaml`, `relevance_rules.yaml`, `interpretation_config.yaml`
**When** the loader runs
**Then** each file parses into a typed config object and missing/malformed files raise a clear startup error (fail fast)
**And** `sources.yaml` entries carry `tier`, `endpoint`, `cadence`, and `authority_rank`.

**Given** any component needing a topic, rule, model ID, or cadence
**When** it reads that value
**Then** it obtains it from the loaded config, and a grep of the codebase shows no hard-coded topic lists, KAD codes, or model IDs.

### Story 0.4: NotionGateway with upsert-by-key and class-aware payloads

As a **developer**,
I want `core/notion_gateway.py` as the sole Notion entry point,
So that all writes are exactly-once upserts and payloads respect the class-aware schema and Notion limits (AD-2, AD-14, FR-17).

**Acceptance Criteria:**

**Given** an Item to persist
**When** `upsert_item()` is called
**Then** it looks up an existing page by `(source_id, source_name)+hash` before creating, updating in place if found — re-running the same write never creates a duplicate page.

**Given** Items of each Content Class
**When** they are written
**Then** Class A writes the full page (metadata + full text child page + interpretation fields), Class B writes metadata + URL only (no full text/snippet beyond title), and Class C writes metadata + transient full text
**And** batches are ≤100 items, throttled to ≤3 req/s, rich text >2000 chars becomes a child page, and a partial-batch failure re-runs only unwritten items (checkpointed).

**Given** a Notion API rate-limit or transient error mid-batch
**When** the gateway retries
**Then** it backs off and resumes from the last checkpoint without re-creating already-written pages.

### Story 0.5: Notion workspace schema & views provisioning

As an **operator**,
I want a provisioning script that creates the Notion databases and views,
So that the legal team's "UI" (the eight views) exists and matches the schema (FR-17, spec §10).

**Acceptance Criteria:**

**Given** a Notion integration token and a parent page
**When** I run the provisioning script
**Then** it creates the main "Legal Intelligence" database with the four class-aware property groups and the three auxiliaries (Reviewers Workload, Ontology Reference, Interpretation Examples, plus a Cost Ledger DB)
**And** it creates the eight views (Recent, Pending Relevance Review, Pending Interpretation Review, Approved & Actionable, By Topic, Critical Deadlines, Index Archive, My Queue)
**And** re-running the script is idempotent (detects existing databases by title/id, does not duplicate them).

### Story 0.6: MeteredLLMClient & Cost Ledger

As an **operator**,
I want every LLM call routed through one metered client that writes a Cost Ledger row,
So that all spend is tracked and attributable, with alert thresholds (AD-7, FR-21).

**Acceptance Criteria:**

**Given** any component needing an LLM
**When** it calls `MeteredLLMClient`
**Then** exactly one Cost Ledger row is written per call (`timestamp, stage, model, input_tokens, output_tokens, usd_cost, item_id, success`) to the Cost Ledger store (Notion aux DB, buffered via local append-only file)
**And** a grep shows no component importing the raw `anthropic`/`claude-agent-sdk` client directly.

**Given** accumulated ledger rows
**When** a monthly report is generated
**Then** it breaks cost down by stage and flags monthly cost >2× baseline and any single-item cost >$1.

### Story 0.7: In-process scheduler & SourceAdapter base contract

As an **operator**,
I want an APScheduler-based scheduler and the `SourceAdapter` base interface,
So that sources run on configured cadences and every source (real or fake) yields Source Records in one shape (FR-19, AD-1, AD-3).

**Acceptance Criteria:**

**Given** `config/sources.yaml` cadences
**When** the scheduler starts
**Then** it registers one job per enabled source at its configured cadence and triggers the ingestion filter for that source.

**Given** the `SourceAdapter` abstract base
**When** any adapter implements it
**Then** it exposes a `fetch()` yielding `SourceRecord`s with the mandatory field set, and a failing adapter isolates to its job without halting the scheduler (AD-12).

### Story 0.8: Structured logging & alerting

As an **operator**,
I want structured JSON logging and an alerting hook,
So that runs are observable and breakage/anomalies notify the ops channel (FR-20, AD-12).

**Acceptance Criteria:**

**Given** any pipeline stage
**When** it runs
**Then** it emits JSON logs with `source, event, status, duration_ms, error, item_id`, and no unstructured `print` logging exists.

**Given** an alert condition (source silent, failed-LLM-rate >5%, scraper zero-result, cost threshold)
**When** it fires
**Then** the alerting module dispatches to a configurable channel (stub/console at MVP, pluggable to Slack/email later) and the alert is logged.

### Story 0.9: End-to-end fake-data walking skeleton

As a **project stakeholder**,
I want a fake source adapter and stubbed triage/interpretation that drive sample Items through the full pipeline into Notion,
So that we prove the whole flow works before building real connectors (Phase 0 gate).

**Acceptance Criteria:**

**Given** a `FakeSourceAdapter` emitting fixture Legal Events (a mix that should become Class A, B, and C) and stub triage/interpretation filters
**When** I run the pipeline end-to-end
**Then** each fake Item traverses New → Awaiting Triage → its Content Class → (for A) Draft Interpretation, and lands in Notion with the correct class-aware payload
**And** a Class B fake Item has no full text in Notion, a Class C fake Item holds transient full text, and a Class A fake Item has a draft interpretation and the disclaimer.

**Given** the test suite
**When** `pytest` runs in CI/local
**Then** an integration test asserts the full traversal (using a mocked or sandbox Notion) is green, and idempotency is verified by running ingestion twice and asserting no duplicate Items.

---

## Epic 1: Tier-1 Collection — Official APIs

**Goal:** Real Legal Events flow from the seven Tier-1 sources into Notion, normalized and language-detected, replacing the fake adapter. Each adapter is independent (AD-3) and isolated on failure (AD-12).

### Story 1.1: Normalization & text-extraction pipeline

As a **developer**,
I want `pipeline/normalize.py` to map any Source Record to a unified Item and extract text from PDF/HTML,
So that downstream stages see one clean schema regardless of source (FR-4).

**Acceptance Criteria:**

**Given** a Source Record with a PDF or HTML body
**When** normalization runs
**Then** plain text is extracted (pdfplumber for PDFs; OCR fallback flagged where a scanned PDF is detected), language is detected (el/en/other), and `hash` = SHA-256 of normalized text.
**And** >99% of normalized Items have non-empty title, date, and URL (data-quality gate); items failing the gate are alerted and skipped, not silently persisted.

### Story 1.2: EUR-Lex / CELLAR adapter

As a **legal counsel**,
I want new EU Regulations, Directives, and CJEU case-law collected from EUR-Lex,
So that EU-level obligations are captured with correct CELEX identity (FR-1).

**Acceptance Criteria:**

**Given** the EUR-Lex Atom feed / SPARQL endpoint and a lookback window from config
**When** the adapter runs
**Then** it yields Source Records keyed on CELEX with title, type, dates, and the official URL, pre-filtered by EuroVoc descriptors from config.
**And** a corrigendum (new CELEX suffix) is emitted as a distinct Legal Event carrying a raw `supersedes_ref` in `raw_metadata` (AD-15).

### Story 1.3: Δι@ύγεια adapter

As a **legal counsel**,
I want decisions/circulars from Δι@ύγεια (covering ΕπΑντ, ΑΑΔΕ, ΕΦΕΤ, ΑΠΔΠΧ, ministries) collected,
So that Greek administrative acts — the most critical source — are captured (FR-1).

**Acceptance Criteria:**

**Given** configured organization UIDs and a date window
**When** the adapter runs
**Then** it yields Source Records keyed on ΑΔΑ with subject→title, decision-type→type, organization→authority, and the PDF `documentUrl`
**And** the PDF flows through normalization for text extraction; a checksum mismatch is logged.

### Story 1.4: Βουλή, EDPB, EFSA, GDPRhub & data.gov.gr adapters

As a **legal counsel**,
I want the remaining Tier-1 sources collected on their cadences,
So that parliamentary early-warning, data-protection, food-safety, and DPA-decision coverage is complete (FR-1).

**Acceptance Criteria:**

**Given** each source's endpoint/feed and config cadence
**When** each adapter runs
**Then** Βουλή bills, EDPB news/documents RSS, EFSA RSS, GDPRhub MediaWiki pages, and data.gov.gr datasets each yield conformant Source Records with correct identity keys.
**And** data.gov.gr uses the free API key from the secret store; any source erroring isolates without affecting the others.

---

## Epic 2: Deduplication & Merge

**Goal:** One Item per Legal Event, with cross-source merge by authority hierarchy, human confirmation for probable duplicates, and correct precedent handling.

### Story 2.1: Weighted duplicate scoring

As a **developer**,
I want `pipeline/dedup.py` to compute an aggregate duplicate score,
So that certain duplicates auto-merge, probable ones go to confirmation, and distinct ones stay separate (FR-5).

**Acceptance Criteria:**

**Given** a candidate Item and existing Items
**When** scoring runs
**Then** it combines the configured weighted signals (exact source_id 1.0, text-hash 0.95, title Levenshtein>0.85 →0.6, authority+date 0.5, topic/entity overlap>70% →0.3) into an aggregate stored in `dedup_score`.
**And** ≥0.95 → auto-merge; 0.70–0.94 → status `Awaiting Dedup Confirmation`; <0.95 distinct — decided via the config, and creation is serialized per key (AD-14) so concurrent polls cannot create two Items.

### Story 2.2: Authority-ranked merge

As a **legal counsel**,
I want merges to keep the most authoritative source's fields while preserving all source links,
So that the official version wins but nothing is lost (FR-5).

**Acceptance Criteria:**

**Given** two Items merging
**When** the merge runs
**Then** metadata and full text come from the highest `authority_rank` source (falling back for full text if the primary lacks it), all source URLs are kept in `additional_sources[]`, and commercial editorial goes to `external_commentary`.
**And** a merge that adds interpretation-relevant fields to an Item already past Interpretation enqueues a re-interpretation rather than mutating an Approved Item (AD-16).

### Story 2.3: Supersedes/precedent relations & dedup-confirmation queue

As a **legal counsel**,
I want superseding versions linked and probable duplicates confirmable by a human,
So that legislative history is traceable and borderline merges are correct (FR-5, FR-22).

**Acceptance Criteria:**

**Given** a superseding version (corrigendum/amendment)
**When** dedup processes it
**Then** it creates a new Item with an Item↔Item `supersedes` relation, the new Item inherits Topics + precedent from its target, and the target is driven through the `Superseded` transition (AD-15).

**Given** an Item in `Awaiting Dedup Confirmation`
**When** a reviewer opens the dedup-confirmation view
**Then** they can confirm-merge or reject-as-distinct, and the decision is recorded and moves the Item to its resolved status.

---

## Epic 3: Tier-2 Collection — Scraping

**Goal:** Coverage of no-API sources via polite, monitored scrapers that alert on breakage rather than fail silently.

### Story 3.1: Shared scraping-politeness middleware

As an **operator**,
I want one politeness middleware all scrapers route through,
So that rate-limiting, jitter, UA rotation, robots.txt, and the circuit breaker are enforced uniformly and the client is never exposed (FR-2, AD-10).

**Acceptance Criteria:**

**Given** any Tier-2 outbound request
**When** it is issued
**Then** it passes through the middleware: ≤1 req/5s per domain with ±30% jitter, non-identifying rotating UA, robots.txt respected, max 1 concurrent/domain, backoff 2/4/8/16/32s.
**And** 3× 429/503 within 5 min pauses that domain for 30 min (circuit breaker); a scraper cannot issue a raw request bypassing the middleware.

### Story 3.2: Change-detection & breakage alerting

As an **operator**,
I want scrapers to detect layout changes and alert,
So that silent coverage loss is impossible (FR-2, R1).

**Acceptance Criteria:**

**Given** a scraper whose result selector returns zero rows
**When** this repeats beyond the configured threshold
**Then** an ops alert fires, the run is marked degraded (not empty-success), and the coverage metric reflects the gap.

### Story 3.3: ΦΕΚ, ΣτΕ, ΕπΑντ, ΕΦΕΤ, RASFF & dpa.gr scrapers

As a **legal counsel**,
I want the six Tier-2 sources scraped on their cadences,
So that ΦΕΚ, ΣτΕ case-law, competition, food recalls, RASFF alerts, and DPA acts are captured (FR-2).

**Acceptance Criteria:**

**Given** each site and its config cadence
**When** each scraper runs
**Then** it yields conformant Source Records; ΕΦΕΤ/RASFF parse product + hazard from titles; ΕπΑντ prefers the Δι@ύγεια path with a weekly direct cross-check; dpa.gr parses HTML acts.
**And** RASFF integration mechanism (scrape vs Apitalks) is a config-selectable per-source choice.

---

## Epic 4: Tier-3 Collection — Commercial Inbox

**Goal:** Cross-validation and safety-net coverage from commercial newsletters, without ever touching a personal mailbox.

### Story 4.1: Shared-inbox newsletter parser

As a **legal counsel**,
I want commercial newsletters in the dedicated shared inbox parsed into the pipeline,
So that anything the official sources miss is still surfaced, tagged as commercial (FR-3).

**Acceptance Criteria:**

**Given** the dedicated shared inbox (`legal-intel@…`)
**When** the parser runs
**Then** it reads only that inbox (never a personal mailbox), extracts links, fetches content, and yields Source Records marked `commercial source`.
**And** commercial records never win metadata over an official Source on merge (AD authority hierarchy); their editorial is preserved in `external_commentary`.

---

## Epic 5: Topic Tagging

**Goal:** Every Item carries Ontology Topics, driven by config, so triage and retrieval have signal.

### Story 5.1: Ontology-driven rule-based tagging

As a **legal counsel**,
I want Items tagged with Topics from the validated Ontology,
So that relevant compliance subjects are identifiable (FR-6).

**Acceptance Criteria:**

**Given** `ontology.yaml` keywords/descriptors
**When** `pipeline/tag.py` runs
**Then** it assigns only Topics defined in the Ontology (an unknown descriptor never creates a Topic), using EuroVoc pre-filtering for EUR-Lex items, and tagging coverage exceeds 90%.

### Story 5.2: LLM tagger for edge cases

As a **legal counsel**,
I want ambiguous Items tagged by an LLM,
So that items keyword rules miss still get Topics (FR-6, AD-7).

**Acceptance Criteria:**

**Given** an Item with no confident rule-based Topic
**When** the LLM tagger runs via the MeteredLLMClient
**Then** it proposes Topics constrained to the Ontology, writes a Cost Ledger row, and its output is validated against the Ontology before persist.

---

## Epic 6: Relevance Triage

**Goal:** The core value — each Item classified A/B/C, cutting 60-70% noise, with class-aware retention and a defensible reason on every decision.

### Story 6.1: Deterministic relevance rules

As a **legal counsel**,
I want explicit include/exclude rules applied before any LLM,
So that certain-relevance and certain-irrelevance items are classified cheaply and predictably (FR-7, AD-8).

**Acceptance Criteria:**

**Given** `relevance_rules.yaml`
**When** `pipeline/triage.py` evaluates an Item
**Then** a direct KAD match (46.35/46.37/46.38/56.10/56.30) or high-priority topic hit forces Class A; an all-excluded-sector item forces Class B; the fired rule id is recorded in the `class_reasoning` envelope (`decided_by: rule`).

### Story 6.2: LLM relevance classifier & triage agent

As a **legal counsel**,
I want rule-undecided Items classified by an LLM against the client profile,
So that ambiguous items get a graded relevance call and clear ones are auto-filed (FR-8, AD-7, AD-13).

**Acceptance Criteria:**

**Given** a rule-undecided Item
**When** the classifier (invoked by the triage stage, which owns the `Awaiting Triage` status per AD-13) runs
**Then** it returns structured JSON (`relevance`, `confidence`, Greek `reasoning`, `sector_touchpoints[]`, `action_signal`, `specialist_needed`), routes high/low-confidence to A/B and everything else to Class C, and writes `class_reasoning` (`decided_by: llm`) and `confidence_score`.

### Story 6.3: Class-aware retention

As a **General Counsel**,
I want retention to follow Content Class,
So that irrelevant items cost nothing and ambiguous ones expire safely (FR-9, AD-5).

**Acceptance Criteria:**

**Given** classified Items
**When** retention runs
**Then** Class B holds metadata+URL only (staging purged), Class C full text is authoritative in Notion with a 7-day staging-mirror TTL (purge-or-promote), and a Class C item past TTL without decision is flagged `overdue`.
**And** promote-to-A verifies full text is present in Notion before flipping class (AD-2).

---

## Epic 7: Interpretation Engine

**Goal:** A structured, reviewable draft legal reading for each Class A Item — the blank-page killer.

### Story 7.1: 7-step structured interpretation with schema validation

As a **legal counsel**,
I want a schema-validated draft interpretation for each Class A Item,
So that I start from a structured first reading, not a blank page (FR-10, AD-9).

**Acceptance Criteria:**

**Given** a Class A Item
**When** `pipeline/interpret.py` runs its steps (legal-type → scope → delta → retrieval → client-impact → actions → confidence)
**Then** the output validates against the pydantic Interpretation schema (summary, before/after/delta, who-affected, client-impact, actions with owner/deadline/priority, critical dates, cited articles, precedents, confidence notes, specialist flags) before any Notion write.
**And** a validation failure fails the Item (alert+skip), never a partial record; the persisted Interpretation is `Draft` and carries the not-legal-advice disclaimer.

### Story 7.2: Retrieval augmentation & few-shot examples

As a **legal counsel**,
I want interpretations grounded in prior related items and gold-standard examples,
So that quality improves over time and matches our style (FR-11).

**Acceptance Criteria:**

**Given** a Class A Item
**When** interpretation runs
**Then** 3–5 related Items (same Topic + authority, last 3 years) are retrieved as context; when none exist (cold start), it proceeds on the Client Context Document alone; gold-standard Interpretation Examples for the Topic are injected as few-shot.

### Story 7.3: Model selection & escalation

As a **General Counsel**,
I want stronger models used only for high-stakes items,
So that quality is high where it matters and cost stays bounded (FR-12, AD-7, AD-8).

**Acceptance Criteria:**

**Given** `interpretation_config.yaml`
**When** interpretation runs
**Then** the default model is used unless an escalation trigger fires (topic ∈ {csrd_scope, epant_decision, ste_decision} or `requires_specialist_review`), in which case the escalation model is used; all model IDs come from config, and every call is metered.

---

## Epic 8: Human Review Workflows & Feedback

**Goal:** The legal team's daily loop in Notion — resolve ambiguity, review interpretations, plan actions — plus reclassify and the weekly quality retro.

### Story 8.1: WF1 — Class C relevance review

As a **legal counsel**,
I want to resolve ambiguous items to A or B from a Notion queue,
So that the machine's uncertainty is cleared with a recorded decision (FR-13, AD-6).

**Acceptance Criteria:**

**Given** the "Pending Relevance Review" view (Class C, assigned/unassigned)
**When** I choose Classify-as-A, Classify-as-B, or Update-Ontology
**Then** A promotes to interpretation (re-fetching full text if needed), B downgrades to index-only (full text discarded), the decision/reason/reviewer/timestamp are recorded, and the SLA clock (2 business days) drives an `overdue` flag on breach.

### Story 8.2: WF2 — Interpretation review with feedback capture

As a **legal counsel**,
I want to approve, edit, reject, or escalate a draft interpretation,
So that only validated readings become Approved and my edits improve the system (FR-14).

**Acceptance Criteria:**

**Given** a `Draft` interpretation in "Pending Interpretation Review"
**When** I Edit+Approve, Reject+Redo, or Escalate
**Then** Edit+Approve captures the field diff as feedback and sets Approved; Reject+Redo regenerates with my notes as added context; SLA is 3 business days (24h if `action_signal = immediate`); routing is topic-based.

### Story 8.3: WF3 — Client-impact & action planning

As a **senior lawyer / compliance head**,
I want to set action status and track deadlines for approved items with actions,
So that obligations turn into tracked work (FR-15).

**Acceptance Criteria:**

**Given** an Approved Item with non-empty actions in "Requires Client Action"
**When** I set a Client Action Status (No action / Advise / Update Policy / Track Deadline / Escalate / Done)
**Then** the status is recorded, and Track-Deadline schedules a reminder before `critical_dates.entry_into_force`.

### Story 8.4: Bidirectional edits & B→A reclassify re-fetch

As a **developer**,
I want reviewer edits to persist and a B→A reclassify to re-fetch full text in place,
So that human changes stick and reclassification works without duplicating Items (FR-18, FR-22, AD-11).

**Acceptance Criteria:**

**Given** a reviewer edits fields or status in Notion
**When** reconciliation runs (webhook or ≤15-min poll)
**Then** edits and status changes are reflected in the system consistently with the state machine.

**Given** a Class B Item flagged Reclassify-to-A
**When** the re-fetch entry point runs
**Then** it hydrates full text in place on the existing Item id (never mints a new Item, even if the re-extracted hash differs) and enqueues Interpretation.

### Story 8.5: Quality Observer weekly retro

As a **General Counsel**,
I want a weekly automated metrics/drift retro,
So that we catch degradation (Class C rate, approval-without-edits, SLA, coverage, reclassification, cost) early (FR-20, spec §9.4).

**Acceptance Criteria:**

**Given** a week of pipeline activity
**When** the Quality Observer agent runs (metered)
**Then** it computes SM-1..SM-7 and the counter-metrics, flags any past its alert threshold, and writes a retro summary to Notion.
