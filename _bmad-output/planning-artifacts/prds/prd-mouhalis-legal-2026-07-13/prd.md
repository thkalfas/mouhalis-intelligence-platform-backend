---
title: Legal Intelligence Collection Layer
status: final
created: 2026-07-13
updated: 2026-07-13
project: mouhalis-legal
storage_path: "Path B — Notion-first (MVP)"
scope_environment: "Environment A — Claude Code production infrastructure"
---

# PRD: Legal Intelligence Collection Layer
*Working title — confirm.*

## 0. Document Purpose

This PRD is for the REBORRN project team (PM, architect, engineers) and the client's legal department, and it feeds the downstream BMAD workflows (Architecture → Epics & Stories → Implementation). It formalizes the source specification in `instructions.md` (v2.0) and `cowork-agents.md` (v1.0) into a capability-first product contract. It describes **Environment A** — the Claude Code production infrastructure that runs 24/7 to collect, normalize, triage, and interpret legal/regulatory events. **Environment B** (the Cowork on-demand agent toolkit) is a downstream consumer of the same Notion system-of-record and is referenced here (§4.9) but specified in `cowork-agents.md`. Vocabulary is Glossary-anchored (§3); features are grouped with globally-numbered FRs; inferred decisions carry inline `[ASSUMPTION]` tags indexed in §12. Technical mechanism choices (SPARQL queries, scraper selectors, model IDs, DB DDL) live in `addendum.md`, not here.

## 1. Vision

The client — a wholesale trader of tobacco and food products with a franchised retail food-service arm (KAD 46.35, 46.37, 46.38, 56.10, 56.30) — operates in one of the most regulation-dense corners of Greek and EU law: tobacco excise and traceability, food safety and labeling, GDPR, ESG reporting, and competition/vertical-agreement rules. Today the legal team relies on commercial subscriptions and manual reading to stay current. Coverage is inconsistent, signal is buried in noise, and the same event arrives three times from three sources while genuinely novel obligations slip through.

The Legal Intelligence Collection Layer is an automated **horizon-scanning → relevance-triage → interpretation** pipeline. It continuously ingests ~15 authoritative Greek and EU sources, deduplicates and normalizes each legal event into a single record, decides whether it actually matters to *this* client, and for the items that do, drafts a structured first-pass legal interpretation — what changed, who is affected, what actions are required, by when. Everything lands in a Notion workspace that is the single source of truth, where the legal team reviews, approves, and acts.

The value is not comprehensiveness for its own sake — it is **discrimination**: cutting 60-70% index-only noise so the team spends its attention on the 20-25% of events that create or change obligations, with a defensible audit trail and a reclassification path for anything the automated layer gets wrong. The system augments legal judgment; it never replaces it. Every interpretation is a reviewable draft carrying the disclaimer that it is not legal advice.

## 2. Target User

### 2.1 Jobs To Be Done

- **As the legal counsel / DPO**, I need to know — reliably and early — when a new law, decision, circular, recall, or opinion creates or changes an obligation for our business, so I am never blindsided by a compliance gap.
- **As the legal counsel**, I need the noise filtered out, so I read ten relevant items a week instead of skimming five hundred.
- **As the legal counsel**, when something *is* relevant, I need a structured first-pass reading (what changed, impact, actions, deadlines) so I start from a draft instead of a blank page.
- **As the General Counsel / compliance head**, I need a defensible audit trail showing what the system saw, how it was classified, who reviewed it, and what we decided.
- **As the GC**, I need confidence that the pipeline itself is compliant (GDPR, copyright, source ToS) and that costs are visible and bounded.
- **As the REBORRN operator**, I need to run this 24/7 with monitoring and alerting, add sources without rework, and prove coverage.

### 2.2 Non-Users (v1)

- The legal team does **not** operate the collection pipeline directly — it runs headless in the background; humans only touch Notion.
- **Not** for end-consumers, external counsel portals, or client-of-client distribution in v1.
- **Not** a case-management or matter-management system; it feeds one, it is not one.

### 2.3 Key User Journeys

- **UJ-1. Eleni, the legal counsel, starts her Monday in a triage queue, not an inbox.**
  Eleni, in-house counsel juggling tobacco excise, food labeling, and GDPR, opens the Notion "Pending Relevance Review" view. Over the weekend the pipeline ingested 180 events; 128 were auto-filed as index-only Class B (she never sees them in her queue), 38 became Class A with draft interpretations, and 14 ambiguous items sit in her Class C queue awaiting a human call. She opens a Class C item — a ministerial decision the classifier scored 0.6 — reads the metadata and snippet, sees it touches food additives, and clicks **Classify as A**. The system re-fetches full text and kicks off interpretation. **Climax:** in one screen she has cleared the machine's uncertainty and the queue reflects it. **Resolution:** the item moves to the interpretation queue; her decision is logged as a labeled example. **Edge case:** if the 2-business-day SLA lapses before she decides, the item is flagged `overdue` and surfaces in a Monday alert.

- **UJ-2. Eleni reviews a draft interpretation of a new EUR-Lex regulation.**
  A Class A item — an amendment to the Tobacco Products Directive traceability rules — arrives with a draft interpretation: a plain-Greek summary, a before/after delta, affected business lines (tobacco_wholesale), new obligations, three required actions with owners and deadlines, and cited articles. Eleni reads it, corrects one deadline the model inferred wrong, edits the operational-impact paragraph, and clicks **Edit + Approve**. **Climax:** an item that would have taken her an afternoon of reading is validated in fifteen minutes. **Resolution:** status → Approved; her edits are captured as training feedback; because `actions_required` is non-empty it appears in "Requires Client Action." **Edge case:** if she disagrees fundamentally she clicks **Reject + Redo** with notes and the interpretation regenerates using her feedback.

- **UJ-3. Giorgos, the operator at REBORRN, catches a broken source before the legal team notices.**
  Giorgos gets an ops alert: the ΦΕΚ scraper's result selector returned zero rows twice in a row — a probable layout change. He opens the monitoring dashboard, sees ΦΕΚ ingestion flatlined while every other source is healthy, confirms the site changed its markup, patches the selector, and re-runs. **Climax:** coverage is restored the same morning; the legal team's Monday coverage report shows 100%. **Resolution:** the incident and fix are logged. **Edge case:** if he can't fix it immediately, the source is marked degraded and the weekly coverage report flags the gap so nobody assumes silence means "no new law."

## 3. Glossary

*Downstream workflows must use these terms verbatim. No synonyms elsewhere in the PRD.*

- **Legal Event** — A single legal or regulatory occurrence: a law, presidential decree (ΠΔ), ministerial decision (ΥΑ), circular (Εγκύκλιος), court decision (Απόφαση), opinion (Γνωμοδότηση), public consultation (Διαβούλευση), or product recall (Ανάκληση). The atomic unit the system collects. One Legal Event maps to exactly one **Item** after deduplication.
- **Item** — The normalized, deduplicated record of a Legal Event in the system of record. Carries a Content Class and passes through the State Machine. One Item may reference many **Source Records**.
- **Source Record** — One raw capture of a Legal Event from one Source, before deduplication. Multiple Source Records (e.g. the same ΦΕΚ from Εθνικό Τυπογραφείο and kodiko.gr) merge into one Item.
- **Source** — An origin of Legal Events, classified into one of three **Tiers**. ~15 sources at MVP.
- **Tier** — Integration class of a Source: **Tier 1** (structured API/RSS/SPARQL), **Tier 2** (scraping), **Tier 3** (commercial newsletter via shared inbox).
- **Content Class** — The relevance decision on an Item: **Class A** (Relevant — full record + interpretation), **Class B** (Index-only — metadata + URL, no full text), **Class C** (Ambiguous — full text held transiently, awaiting human decision).
- **Triage** — The step that assigns a Content Class, via deterministic rules first, then an LLM classifier for undecided items.
- **Interpretation** — The structured first-pass legal analysis generated for each Class A Item (§4.5 schema). A reviewable Draft, never final legal advice.
- **Ontology** — The client-validated set of compliance **Topics** with keywords, authorities, and priority, stored in `ontology.yaml` and mirrored to Notion. Drives Topic tagging.
- **Topic** — A compliance subject in the Ontology (e.g. `vertical_agreements`, `tobacco_traceability`). Items carry one or more Topics.
- **Relevance Rules** — Deterministic include/exclude rules in `relevance_rules.yaml`, evaluated before the LLM classifier.
- **State Machine** — The explicit status lifecycle every Item follows (§4.7), managed automatically by the pipeline with defined human-controlled transitions.
- **System of Record** — The Notion "Legal Intelligence" database and its auxiliaries; the single source of truth shared by Environment A and Environment B.
- **Class C TTL** — The 7-day time-to-live on transiently-held Class C full text.
- **Reclassification** — A human-initiated Content Class change, notably B→A, which triggers re-fetch of full text from the Source and a fresh Interpretation.
- **Cost Ledger** — The per-LLM-call record of stage, model, tokens, and USD cost used for cost reporting and alerting.
- **Environment A** — The Claude Code production infrastructure (this PRD's scope).
- **Environment B** — The Cowork on-demand agent toolkit for the legal team (specified in `cowork-agents.md`).

## 4. Features

### 4.1 Multi-Source Collection (3-Tier)

**Description:** The system continuously collects Legal Events from ~15 authoritative sources across three integration Tiers, each source polled on its own cadence. Tier 1 sources (EUR-Lex/CELLAR, Βουλή, Δι@ύγεια, EDPB, EFSA, GDPRhub, data.gov.gr) use official APIs/RSS/SPARQL. Tier 2 sources (Εθνικό Τυπογραφείο/ΦΕΚ, ΣτΕ, ΕπΑντ, ΕΦΕΤ, RASFF, dpa.gr) are scraped with change-detection and politeness controls. Tier 3 is commercial newsletters landing in a dedicated shared inbox, parsed for cross-validation and safety-net coverage. Each capture becomes a Source Record with the full field set (§1.5 of spec). Realizes UJ-1, UJ-3. `[ASSUMPTION: MVP ships Tier 1 first, then Tier 2, then Tier 3, per spec Phase 1 ordering; exact source count may flex as endpoints are verified during implementation.]`

**Functional Requirements:**

#### FR-1: Tier 1 API ingestion
The system can poll each configured Tier 1 Source on a schedule and emit one Source Record per new Legal Event. Realizes UJ-1.

**Consequences (testable):**
- Each Tier 1 Source produces Source Records carrying all mandatory fields: `source_id`, `source_name`, `title`, `type`, `authority`, `date_published`, `url`, `raw_metadata`, `collected_at`, `hash`.
- A Source Record already seen (same `source_id` + `source_name`) updates `last_seen_at` and does **not** create a duplicate (idempotency).
- Transient errors (5xx, timeout) retry with exponential backoff up to 5 attempts; permanent errors (404, schema change) alert and skip without crashing the run.
- EUR-Lex corrigenda (new CELEX suffix) are treated as distinct Legal Events with a `supersedes` relation to the prior Item.

#### FR-2: Tier 2 scraping with change-detection
The system can scrape each configured Tier 2 Source, detect when its result-listing markup changes, and alert operators on breakage. Realizes UJ-3.

**Consequences (testable):**
- Each scraper respects robots.txt, uses non-identifying rotating browser User-Agents, rate-limits to ≤1 request / 5 sec per domain with ±30% jitter, and runs max 1 concurrent request per domain.
- A circuit breaker pauses a domain for 30 minutes after 3+ 429/503 responses within 5 minutes.
- When a scraper's expected selector returns zero results (probable layout change), an ops alert fires and the run is marked degraded, not silently empty.

#### FR-3: Tier 3 commercial-inbox intake
The system can ingest commercial newsletters delivered to a dedicated shared inbox (never the counsel's personal mailbox), extract links, fetch content, and tag records as `commercial source`.

**Consequences (testable):**
- Intake reads only the dedicated shared inbox; no personal mailbox is accessed.
- Extracted items are marked as commercial-source and used for cross-validation/safety-net, never as the primary metadata source when an official Source exists (§4.2 merge policy).

**Notes:** `[NOTE FOR PM]` Shared-inbox provisioning (`legal-intel@client-domain`) and forwarding rules are a client-side prerequisite; the intake parser is in scope, the mailbox setup is a dependency (§9).

### 4.2 Normalization & Deduplication

**Description:** Every Source Record is normalized into the unified schema (text extracted from PDF/HTML, language detected) and deduplicated into a single Item. Deduplication uses weighted matching signals (exact `source_id`, SHA-256 text hash, title similarity, authority+date, topic/entity overlap) yielding an aggregate score that auto-merges near-certain duplicates, routes probable duplicates to human confirmation, and keeps distinct items separate. A ranked source-authority hierarchy decides which Source's fields win on merge, while all Source URLs are retained. Realizes UJ-1.

**Functional Requirements:**

#### FR-4: Normalization to unified schema
The system can map any Source Record into the unified Item schema, extracting plain text from PDF and HTML and detecting language (el/en/other).

**Consequences (testable):**
- PDF-only sources (Δι@ύγεια, ΑΑΔΕ, EDPB) yield extracted text; scanned PDFs are OCR'd.
- Each normalized Item has a `hash` = SHA-256 of normalized full text.
- >99% of Items have non-empty title, date, and URL; >90% carry at least one Topic (data-quality gates).

#### FR-5: Weighted deduplication
The system can compute an aggregate duplicate score for a candidate Item against existing Items and act on thresholds.

**Consequences (testable):**
- Score ≥ 0.95 → auto-merge; 0.70–0.94 → probable-duplicate routed to human confirmation (Class C queue); < 0.70 → treated as distinct.
- On merge, metadata and full text come from the highest-ranked Source in the authority hierarchy; if the primary lacks full text, fall back to the next Source that has it.
- All contributing Source URLs are preserved in `additional_sources[]`; commercial editorial commentary is preserved in `external_commentary` for the interpretation stage.
- A superseding version (corrigendum/amendment) creates a new Item with a `supersedes` relation and re-triggers Interpretation.

### 4.3 Topic Tagging (Ontology-Driven)

**Description:** Each normalized Item is tagged with one or more Topics from the client-validated Ontology. Tagging is rule-based first (keyword and descriptor matches from `ontology.yaml`), with an LLM classifier for edge cases. The Ontology spans horizontal topics (corporate, labor, tax, myDATA), data protection, ESG, food, franchise/competition, tobacco (critical), and retail/food-service. Realizes UJ-2.

**Functional Requirements:**

#### FR-6: Ontology-based topic assignment
The system can assign Topics to an Item using Ontology keywords/descriptors, escalating ambiguous cases to an LLM tagger.

**Consequences (testable):**
- Topics assigned are drawn only from the validated Ontology; an unrecognized descriptor does not silently create a Topic.
- EuroVoc descriptors on EUR-Lex items pre-filter to candidate Topics before tagging.
- Tagging coverage (Items with ≥1 Topic) exceeds 90%.

**Notes:** `[NOTE FOR PM]` The Ontology itself is a **client deliverable** validated in a 90-minute workshop before production tagging (§9). MVP/Phase 0 uses the spec's draft topic list as a placeholder.

### 4.4 Relevance Triage (Class A / B / C)

**Description:** After tagging, each Item is triaged into a Content Class. Deterministic Relevance Rules run first: explicit include rules (high-priority topic hits, authority+sector, direct KAD-code mention) force Class A; explicit exclude rules (unrelated sectors, personnel appointments, boilerplate) force Class B. Undecided Items go to an LLM classifier grounded in the client profile, which returns relevance, confidence, reasoning (in Greek), sector touchpoints, and action signal. High-confidence high/low relevance become A/B; everything else becomes Class C for human review. Realizes UJ-1.

**Functional Requirements:**

#### FR-7: Deterministic relevance rules
The system can evaluate `relevance_rules.yaml` include/exclude rules against an Item and assign Class A or B without an LLM call when a rule is decisive.

**Consequences (testable):**
- A direct KAD-code match (46.35, 46.37, 46.38, 56.10, 56.30) in the text forces Class A.
- An Item whose Topics are all in the excluded-sector set and matches no include rule is forced Class B.
- Rule evaluation is deterministic and logged (which rule fired) for the Explain Classification path (§4.9).

#### FR-8: LLM relevance classifier
The system can classify rule-undecided Items with an LLM against the client profile and route by confidence.

**Consequences (testable):**
- Returns structured JSON: `relevance` (high/medium/low), `confidence` (0–1), `reasoning` (Greek), `sector_touchpoints[]`, `action_signal`, `specialist_needed`.
- relevance=high & confidence>0.85 → Class A; relevance=low & confidence>0.85 → Class B; all else → Class C.
- The classifier prefers Class C (medium) over guessing when uncertain; every decision writes a `class_reasoning`.

#### FR-9: Class-aware retention
The system retains data per Content Class: Class A keeps metadata + full text + interpretation; Class B keeps only metadata + URL (no full text, staging purged); Class C holds full text in staging under a 7-day TTL.

**Consequences (testable):**
- Class B Items carry no full text or snippet beyond title; their staging record is purged after classification.
- Class C full text is purged when the item resolves to B, promoted to permanent when resolved to A, and flagged `overdue` if the TTL lapses without decision.
- Class B → A Reclassification re-fetches full text from `url` before Interpretation.

### 4.5 Interpretation Engine (Class A)

**Description:** For each Class A Item the system generates a structured Interpretation via a multi-step LLM pipeline (legal-type ID → scope → delta → retrieval augmentation → client-specific impact → action extraction → confidence self-assessment). Output is a fixed JSON schema: summary, what-changed (before/after/delta), who-affected, client-impact, actions-required (owner/deadline/priority), critical dates, cited articles, related precedents, confidence notes, and specialist-review flags. It is a Draft carrying the not-legal-advice disclaimer. Realizes UJ-2.

**Functional Requirements:**

#### FR-10: Structured interpretation generation
The system can produce a schema-conformant Interpretation for a Class A Item and store it as a Draft.

**Consequences (testable):**
- Output validates against the Interpretation JSON schema (§8.2 of spec); missing required fields fail the run rather than producing a partial silent record.
- Every Interpretation enters status `Draft` and is not visible in the Approved Notion view until human review.
- Each Interpretation carries the disclaimer text verbatim.

#### FR-11: Retrieval-augmented, few-shot interpretation
The system can enrich the interpretation prompt with related prior Items (same Topic + authority, last 3 years) and curated gold-standard examples.

**Consequences (testable):**
- 3–5 related Items are retrieved and injected as precedent context; when none exist (cold start), the run proceeds on the Client Context Document alone.
- Items flagged as gold-standard examples are used as few-shot exemplars for same-Topic future items.

#### FR-12: Model selection & escalation
The system uses a default model for volume and escalates to a stronger model for high-stakes topics or self-flagged uncertainty.

**Consequences (testable):**
- Configurable escalation triggers (topic in {csrd_scope, epant_decision, ste_decision} or `requires_specialist_review=true`) route to the escalation model.
- Model IDs, temperature, and token caps are config-driven (`interpretation_config.yaml`), not hard-coded. `[ASSUMPTION: exact model IDs are resolved at build time against current availability; the spec's named IDs are treated as placeholders.]`

### 4.6 Human-in-the-Loop Review Workflows

**Description:** Three workflows require a human, all operated inside Notion views: (WF1) ambiguous-relevance review of Class C, (WF2) interpretation review of Class A Drafts, (WF3) client-impact & action planning post-approval. Assignment is expertise/round-robin based; each has an SLA; every decision is timestamped for metrics. Human decisions feed back as labeled examples and prompt-tuning signal. Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-13: Class C relevance review (WF1)
A reviewer can resolve a Class C Item to A or B from the "Pending Relevance Review" view, with the decision and reason recorded.

**Consequences (testable):**
- Actions available: Classify as A (→ interpretation), Classify as B (→ index-only, full text discarded), Update Ontology (opens change request).
- Records decision, reason (dropdown), reviewer, and timestamp; SLA = 2 business days; breaches flag `overdue`.

#### FR-14: Interpretation review (WF2)
A reviewer can Approve, Edit+Approve, Reject+Redo, or Escalate a Draft Interpretation, with edits tracked. Realizes UJ-2.

**Consequences (testable):**
- Edit+Approve captures the diff (original vs approved) as training feedback; Reject+Redo regenerates with reviewer notes as added context.
- SLA = 3 business days standard, 24h for `action_signal = immediate`.
- Topic-based expertise routing (e.g. GDPR → DPO, competition → competition lawyer).

#### FR-15: Client-impact & action planning (WF3)
For Approved Items with non-empty actions, a senior reviewer can set a Client Action Status and track deadlines from the "Requires Client Action" view.

**Consequences (testable):**
- Action statuses: No action / Advise / Update Policy / Track Deadline / Escalate / Done.
- Deadline tracking schedules a reminder before `critical_dates.entry_into_force`.

### 4.7 System of Record: Notion State Machine & Schema

**Description:** Notion is the single source of truth. Every Item flows through an explicit State Machine with statuses the pipeline sets automatically and specific transitions humans control. The schema is class-aware (fields kept depend on Content Class) across one main database (Legal Intelligence) and three auxiliaries (Reviewers Workload, Ontology Reference, Interpretation Examples), with eight predefined views. Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-16: Explicit state machine
The system enforces the Item status lifecycle with observable transitions.

**Consequences (testable):**
- Statuses at minimum: New → Awaiting Triage → {Class A - Awaiting Interpretation | Class B - Indexed | Class C - Awaiting Human Review} → Class A - Draft Interpretation → {Approved | Rejected | Requires Action} → Archived.
- Pipeline sets automatic transitions; human-only transitions (approve/reject/reclassify) cannot be triggered by the pipeline.
- Rejected interpretations return to the Interpretation step with reviewer feedback attached.

#### FR-17: Class-aware Notion sync
The system writes class-appropriate payloads to Notion: full pages for Class A, minimal records for Class B, transient full-text-bearing records for Class C.

**Consequences (testable):**
- Batch inserts ≤100 items/batch; respects Notion 3 req/sec rate limit; rich text >2000 chars → child page; full text >100KB → attachment.
- Class B pages contain no full text; the URL links to the official Source.

#### FR-18: Bidirectional sync
Reviewer edits in Notion propagate back to the system's normalized store.

**Consequences (testable):**
- Notion→system reconciliation runs on a bounded cadence (webhook preferred, else ≤15-min polling); edited interpretation fields and status changes are reflected.

**Notes:** `[ASSUMPTION: Under Path B (Notion-first, chosen for MVP), Notion *is* the normalized store; "bidirectional sync" reduces to in-place edits plus an optional export. FR-18's polling model becomes fully relevant only if/when Path A (external DB) is adopted. Confirmed against §3.1.]`

### 4.8 Orchestration, Scheduling, Monitoring & Cost Tracking

**Description:** A scheduler runs each Source and pipeline stage on its cadence (30 min to weekly). The system emits structured logs and metrics, dashboards ingestion health and pipeline throughput, alerts on breakage and SLA/coverage/cost anomalies, and records every LLM call in the Cost Ledger with a monthly cost report. Realizes UJ-3.

**Functional Requirements:**

#### FR-19: Scheduled orchestration
The system runs sources and stages on configured schedules with per-source frequency.

**Consequences (testable):**
- Cadences honored per spec §6 table (e.g. EUR-Lex Atom 30 min, Δι@ύγεια 6h, ΦΕΚ 2×/day, ΕΦΕΤ/RASFF every 4h).
- A stage failure isolates to its source/item and does not halt the whole pipeline.

#### FR-20: Monitoring, logging & alerting
The system produces structured JSON logs, tracks per-source metrics, and alerts on failures and anomalies.

**Consequences (testable):**
- Logs carry `source`, `event`, `status`, `duration_ms`, `error`.
- Metrics: items/day per source, dedup rate, tagging coverage, source→Notion latency.
- Alerts fire on scraper breakage, failed-LLM-call rate >5%, source silent >30 days, and SLA/coverage threshold breaches.

#### FR-21: Cost ledger & reporting
The system records every LLM call and generates a monthly cost report by component.

**Consequences (testable):**
- Each call logs `timestamp`, `stage`, `model`, `input_tokens`, `output_tokens`, `usd_cost`, `item_id`, `success`.
- Alerts: monthly cost >2× baseline, single-item cost >$1.
- Cowork agent usage (Environment B) is attributable via a `source: cowork_[agent]` tag in the same ledger.

### 4.9 Cowork Agent Layer (Downstream — Reference Only)

**Description:** Environment B is a suite of eight on-demand agents (Explain Classification, Reclassify, Similar Cases, Deep Dive, Client Communication Draft, Policy Update Draft, Ontology Refinement Assistant, Weekly Digest) the legal team invokes ad-hoc against the same Notion System of Record. It is **out of scope for this PRD's build** but constrains Environment A's design: the pipeline must persist the fields these agents read (notably `class_reasoning`, `additional_sources`, `external_commentary`, precedent relations) and honor the shared state contract. Full spec in `cowork-agents.md`.

**Functional Requirements:**

#### FR-22: Shared-state contract for Environment B
The system persists all fields and relations Environment B agents depend on, and exposes a re-fetch capability the Reclassify agent can trigger.

**Consequences (testable):**
- `class_reasoning`, `confidence_score`, `additional_sources[]`, `external_commentary`, and precedent relations are populated and readable in Notion.
- A B→A re-fetch entry point exists that re-pulls full text from `url` and enqueues Interpretation.

**Out of Scope:** Building the Cowork agents themselves — deferred to the `cowork-agents.md` track after the System of Record holds meaningful data (100-200 Items).

## 5. Non-Goals (Explicit)

- The system does **not** provide definitive legal advice; every output is a reviewable draft with a disclaimer.
- It does **not** attempt comprehensive capture of all Greek/EU law — only what is relevant to the client's sectors, with index-only records for the rest.
- It does **not** replace the legal team's judgment, commercial subscriptions, or matter-management tooling.
- It does **not** store full text for Class B (irrelevant) items.
- It does **not** access the counsel's personal mailbox.
- It is **not** becoming a general-purpose regulatory product for other clients in v1.
- Environment B (Cowork agents) is **not** built in this track.

## 6. MVP Scope

### 6.1 In Scope

- **Path B (Notion-first)** storage architecture — Notion as the single normalized store; no external DB at MVP.
- **Phase 0 scaffolding**: repo structure, Notion schema, orchestration skeleton, Cost Ledger, monitoring — validated end-to-end with **fake data** before investing in 10+ connectors.
- **Phase 1 collection**: Tier 1 sources first, then Tier 2, then Tier 3.
- **Phase 2 triage & interpretation** agents (Triage, Interpretation, Quality Observer) via the Claude Agent SDK.
- **Phase 3 human workflows & Notion views/notifications.**
- Cost tracking, monitoring, alerting from Phase 0 onward.

### 6.2 Out of Scope for MVP

- **Path A (external PostgreSQL backend)** — deferred; adopt only above ~50k Items or when heavy analytics is needed. `[NOTE FOR PM: migration path preserved via Notion→Postgres export retaining IDs.]`
- **The eight Cowork agents** — deferred to the Environment B track (dependency: populated Notion).
- **pgvector/semantic retrieval** — MVP uses keyword/topic-based retrieval; semantic is a v2 lever.
- **Calibration on the 100 pre-labeled golden set** — this is Phase 4, after collection + agents run on real data.
- **Full production launch & iterative refinement** — Phase 5.
- **Fine-tuned local models** (Llama/Mistral) — contingency only if copyright/confidentiality forces it.

## 7. Success Metrics

*Each SM cross-references the FRs it validates. Targets from spec §9.5; counter-metrics prevent optimizing the wrong thing.*

**Primary**
- **SM-1: Class C rate** — Class C Items / total Items (rolling 30 days). Target < 15%; alert > 25%. Validates FR-7, FR-8. *(Measures triage decisiveness — too much ambiguity dumps load on humans.)*
- **SM-2: Interpretation approval-without-edits rate** — approvals with zero field diffs / total approvals. Target > 40%; alert < 20%. Validates FR-10, FR-11, FR-14. *(Measures interpretation quality.)*
- **SM-3: Coverage** — sources that produced content / sources that should have. Target > 95%; alert < 90%. Validates FR-1, FR-2, FR-19, FR-20. *(Silence must never be mistaken for "no new law.")*

**Secondary**
- **SM-4: Median time to interpretation approval** — median(Reviewed At − Draft Created At) in business hours. Target < 3 business days; alert > 5. Validates FR-14.
- **SM-5: Reclassification B→A rate** — Items changed B→A / total B (quarterly). Target < 5%; alert > 10%. Validates FR-7, FR-8, FR-9. *(Too high ⇒ rules/classifier too strict, real items are being buried.)*
- **SM-6: SLA compliance** — % Class C decided ≤2 business days (target >90%) and % Class A reviewed ≤3 business days (target >85%). Validates FR-13, FR-14.
- **SM-7: Reviewer workload balance** — max/mean Items assigned per reviewer. Target < 1.5; alert > 2.0. Validates FR-13, FR-14.

**Counter-metrics (do not optimize)**
- **SM-C1: Class B share must not be pushed up to make SM-1 look good.** If Class B share climbs while SM-5 (B→A reclassification) also rises, the system is hiding relevant items to reduce ambiguity. Counterbalances SM-1.
- **SM-C2: Approval-without-edits must not be gamed by reviewers rubber-stamping.** Track alongside a periodic audit of a random approved sample. Counterbalances SM-2.
- **SM-C3: Cost per relevant item must stay bounded** — total LLM spend / Class A Items. A falling Class C rate bought with runaway Opus escalation is a false economy. Counterbalances SM-1/SM-2. Validates FR-21.

## 8. Cross-Cutting NFRs

- **Reliability:** Runs 24/7 headless; a single source or item failure never halts the pipeline (FR-19). Transient errors retry with backoff (max 5); permanent errors alert-and-skip.
- **Scraping politeness & discretion:** ≤1 req/5s per domain, ±30% jitter, non-identifying User-Agents, robots.txt respected, circuit breaker on repeated 429/503 (FR-2). Rationale: avoid publisher-side blocking and avoid exposing the client.
- **Performance/latency:** Source→Notion latency tracked per source (FR-20); no hard real-time SLA except recall/food-safety sources polled every 4h.
- **Observability:** Structured JSON logs, per-source metrics, weekly "what came in / what didn't / what broke" report to the legal team.
- **Data quality:** <1% Items with empty title/date/URL; >90% with a Topic; dedup-rate baseline tracked with spike alerts.
- **Cost:** MVP LLM spend target $15-30/month under Path B (spec §12); per-item and monthly cost alerts (FR-21).

## 9. Integration & Dependencies

- **Notion** — System of Record. Requires a Notion integration with read-write on Legal Intelligence + read-only on Ontology; API rate limit 3 req/sec. `[ASSUMPTION: client provides a Notion workspace + integration token; MVP may use a REBORRN-owned workspace during Phase 0.]`
- **Anthropic API (Claude Agent SDK)** — Triage, Interpretation, Quality Observer agents. Requires API key + budget.
- **Dedicated shared inbox** (`legal-intel@client-domain`) — client-side provisioning + BCC/forward rules (FR-3 prerequisite).
- **Client Ontology** — validated `ontology.yaml` from the 90-minute legal workshop (FR-6 prerequisite for production tagging).
- **Client Context Document** (~2 pages) — business overview, entities, historical sensitivities, known obligations, risk appetite; injected into Interpretation (FR-10/11 cold-start input).
- **Source endpoints** — public APIs (no auth) except data.gov.gr (free API key); scraper selectors must be verified against live sites at build time.
- **Optional third-party** — Apitalks RASFF wrapper (paid) as an alternative to scraping RASFF.

## 10. Compliance & Regulatory (the system itself)

- **GDPR:** Legal basis = legitimate interest (corporate legal compliance). The system processes no personal data beyond names of lawyers/judges already public in decisions. A data-subject-deletion process exists (locate + delete + confirm).
- **Copyright:** Public-body laws/decisions are public domain in the EU and stored freely. Commercial newsletters/commentary are copyrighted — kept for internal use only, never reproduced verbatim; interpretations summarize, they do not copy.
- **Attribution:** The official Source URL is always retained and shown in Notion for traceability.
- **Terms of Service:** Each Source's ToS is reviewed before activation; Tier 3 automated-processing terms respected.
- **Audit trail / provenance:** Every classification (`class_reasoning`), review (reviewer + timestamps), and reclassification is recorded; trailing 90-day audit available to GC.

## 11. Data Governance & Retention

- Raw Source payloads: retained 12 months for audit.
- Normalized Items (Class A): indefinite.
- Class B index-only: indefinite (minimal footprint).
- Class C staging full text: **7-day TTL** (Class C TTL), then purge-or-promote.
- Full legislative text (public): indefinite.
- No data leaves the Notion/Anthropic perimeter beyond the inference API calls required to run the pipeline.

## 12. Risk & Mitigations

- **R1 — Scraper fragility (Tier 2).** Layout changes silently zero out coverage. *Mitigation:* change-detection + zero-result alerts (FR-2), coverage metric SM-3, cross-check via Tier 1/kodiko.gr.
- **R2 — Over-aggressive Class B filtering buries relevant law.** *Mitigation:* SM-5 reclassification rate + SM-C1 counter-metric; Class C bias when uncertain (FR-8).
- **R3 — Interpretation hallucination / wrong deadlines.** *Mitigation:* mandatory human review (WF2), confidence self-assessment + specialist flag (FR-10), schema validation, disclaimer, edit-feedback loop.
- **R4 — Ontology not delivered on time.** *Mitigation:* Phase 0 runs on the draft topic list; production tagging gated on the validated `ontology.yaml`. `[NOTE FOR PM: client dependency — track explicitly.]`
- **R5 — Cost runaway (Opus escalation loops).** *Mitigation:* per-item + monthly cost alerts (FR-21), SM-C3, escalation caps.
- **R6 — Source ToS / rate-limit backlash.** *Mitigation:* politeness controls (FR-2/NFRs), ToS review before activation, circuit breaker.
- **R7 — Notion scale/performance beyond ~50k Items.** *Mitigation:* Path A migration path preserved (§6.2); Class B minimalism keeps volume down.

## 13. Rollout (Phased)

Mirrors spec §1.3. Phase gates are the deployment checklist (spec Appendix A).

- **Phase 0 — Scaffolding (this session's build target):** repo, Notion schema, orchestration skeleton, Cost Ledger, monitoring — proven with fake data end-to-end.
- **Phase 1 — Collection:** Tier 1 → Tier 2 → Tier 3; 2-week shadow run; legal sign-off on data quality.
- **Phase 2 — Triage & Interpretation agents:** on fake items first, then real; classifier tested on 100-item golden set.
- **Phase 3 — Human workflows & Notion polish:** views, review flows, notifications; Environment B piloting begins.
- **Phase 4 — Calibration:** threshold tuning + prompt refinement on the golden set.
- **Phase 5 — Production launch + iterative refinement.**

## 14. Open Questions

1. Notion workspace ownership at MVP — client-provided vs REBORRN-owned during Phase 0? (§9)
2. Ontology workshop scheduling — what is the realistic delivery date for validated `ontology.yaml`? (R4)
3. RASFF integration — scrape (free) vs Apitalks (paid, low-effort)? (§9)
4. Which Anthropic model IDs are current/approved for tagging, classification, interpretation-default, and escalation at build time? (FR-12)
5. Reviewer roster + expertise routing map — who owns which Topic domains? (FR-13/14)
6. Is the Client Context Document available, or do we bootstrap from existing memos/opinions? (§9)
7. Notification channel for ops + legal alerts — Slack, email, or both? (FR-20)

## 15. Assumptions Index

- §4.1 — MVP ships Tier 1 → Tier 2 → Tier 3; exact source count may flex as endpoints are verified.
- §4.5 — Anthropic model IDs in the spec are placeholders; resolved at build time against availability.
- §4.7 — Under Path B, Notion is the normalized store; "bidirectional sync" reduces to in-place edits + optional export; full sync relevant only under Path A.
- §9 — Client provides Notion workspace + integration token; Phase 0 may run in a REBORRN-owned workspace.
- §13 — Phase ordering follows spec §1.3; Phase 0 fake-data validation precedes real connectors.
