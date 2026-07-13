# HANDOFF — Legal Intelligence Collection Layer

*Read this first when picking the project up in a new Claude Code session (any machine). It replaces the machine-local memory, which does not travel with this folder.*

## What this is

An automated legal/regulatory **horizon-scanning → relevance-triage → interpretation** pipeline for a REBORRN client — a wholesale trader of tobacco and food products with a franchised retail food-service arm (KAD 46.35, 46.37, 46.38, 56.10, 56.30). It ingests ~15 Greek/EU sources, deduplicates and classifies each legal event, and drafts a structured first-pass interpretation for the ones that matter. **Notion is the single source of truth** the legal team works in.

This repo is **Environment A** — the production pipeline. **Environment B** (8 on-demand "Cowork" agents for the legal team) is a separate downstream track, specified in `cowork-agents.md`, not built here.

## Source of truth for the design

- `instructions.md` — the original Environment A spec (v2.0)
- `cowork-agents.md` — the Environment B spec (v1.0)
- `_bmad-output/planning-artifacts/` — the generated BMAD artifacts:
  - `prds/…/prd.md` — PRD: 9 features, **22 FRs (FR-1..FR-22)**, metrics, compliance/risk
  - `architecture/…/ARCHITECTURE-SPINE.md` — **16 architecture decisions (AD-1..AD-16)**; read this before touching code
  - `epics.md` — **9 epics / 30 stories**, full FR coverage — *the build plan*
  - `.memlog.md` files — decision/audit trail for the PRD and architecture runs

## Key decisions (don't re-litigate)

- **Storage: Path B (Notion-first)** — Notion is the normalized store; no external DB at MVP.
- **Scope: Environment A only** this track.
- **Paradigm: pipes-and-filters over a Notion blackboard** — each stage is an idempotent filter reading Items in one `status` and writing them in the next; `status` is the only coordination pipe (AD-1). Notion's lack of coordination primitives is handled explicitly by AD-13..AD-16 (single-consumer statuses, key-serialized upserts, dedup-owned precedence, no silent late mutation).

## Status: Phase 0 ✅ + Epics 1–8 ✅ — **Environment A feature-complete**

**Epic 0 (walking skeleton)** — the full flow runs offline on fake data:
`src/legal_intel/` = core contracts (models, state machine, config-as-data, `NotionGateway` with upsert-by-key idempotency, `MeteredLLMClient`), the pipeline (normalize → dedup → tag → triage → interpret), and platform services (scheduler, cost ledger, logging, alerting, scraping politeness). Backends are pluggable — local store + fake LLM by default (offline), real Notion/Anthropic lazy-imported for later.

**Epic 1 (Tier-1 real adapters) — implemented and tested** (FR-1, FR-4):
- `pipeline/extract.py` — real text extraction (pdfplumber for PDF, stdlib HTML→text), scanned-PDF `needs_ocr` flag, three-way `el/en/other` language detection. `pipeline/normalize.py` now extracts from an adapter-downloaded `raw_body` (adapters download; normalization extracts — the single FR-4 filter).
- `platform/http.py` — shared Tier-1 `HttpClient`: exponential backoff on 429/5xx (`TransientError`), `PermanentError` on 404. `httpx` lazy-imported by the default transport only; adapters take an injected client so **all adapter tests run offline** against fixtures.
- `adapters/` — `eurlex` (SPARQL + CELEX REST, EuroVoc pre-filter, corrigendum→`supersedes_ref`), `diavgeia` (opendata search per org UID, PDF download + checksum check), `rss` (config-driven, serves EDPB + EFSA), `vouli`, `gdprhub` (MediaWiki recentchanges + wikitext), `datagovgr` (API key from the secret store). All endpoints/windows/UIDs/descriptors live in `config/sources.yaml` `options:` (AD-8).
- `adapters/registry.py` — maps the `adapter` key in `sources.yaml` to its class (lazy-imported); the CLI/scheduler build enabled sources from config. Real Tier-1 sources ship `enabled: false` until their prerequisites (below) are signed off.

**Epic 2 (Deduplication & Merge) — implemented and tested** (FR-5, AD-14/15/16):
- `pipeline/dedup.py` rewritten: config-driven weighted signals (`config/dedup.yaml` → `DedupConfig`, AD-8) with a **capped-sum** aggregate into `dedup_score`; thresholds route to auto-merge / `Awaiting Dedup Confirmation` / distinct.
- **Authority-ranked, identity-preserving merge** — the surviving Item always keeps the *first-seen* `page_id`/identity (stable upsert key, no duplicate page regardless of arrival order — this fixed a latent bug where a higher-authority source arriving *second* would have minted a second page); authority governs *content* fields via the new `Item.primary_source`. All source URLs kept in `additional_sources[]`, commercial editorial in `external_commentary`.
- **AD-16** — a content-changing merge onto an already-interpreted Item enqueues re-interpretation (routes back to `Class A - Awaiting Interpretation` for a fresh draft) instead of mutating an Approved reading. New pipeline transitions added for this.
- **AD-15 supersession** — a superseding version (e.g. an EUR-Lex corrigendum, carried via `raw_metadata.supersedes_ref` → `Item.supersedes_ref`) becomes a distinct Item that links `supersedes` to its predecessor, inherits its Topics, and drives the predecessor through `Superseded`.
- **Dedup-confirmation queue** — `dedup.confirm_merge()` / `reject_as_distinct()` (HUMAN actor) resolve `Awaiting Dedup Confirmation` items.

**Epic 3 (Tier-2 Collection — scraping) — implemented and tested** (FR-2, AD-10):
- `platform/scrape_client.py` — the single choke point for all Tier-2 requests. Layers the Phase-0 `PolitenessMiddleware` into a real fetch flow: ≤1 req/5s per domain + ±30% jitter, non-identifying rotating UA, robots.txt respect (fail-open), max-1-concurrent-per-domain lock, backoff 2/4/8/16/32s, circuit breaker (3× 429/503 in 5min → 30min pause). Fetcher/clock/sleep/jitter/UA are injectable seams → fully offline-tested; the default fetcher is lazy-httpx (a Playwright fetcher can be injected for JS-heavy sites).
- `adapters/tier2.py` — `RowExtractor` (stdlib HTML row parser, no bs4), `Tier2Scraper` base (fetches only via the ScrapeClient; a zero-row listing is a *degraded* run that fires an ops alert, never a silent empty-success; content-hash change-detection short-circuits unchanged listings), and the config-driven `HtmlListScraper`.
- Six scrapers (Story 3.3): `fek`/`ste`/`efet`/`dpa` are `HtmlListScraper` + config; ΕΦΕΤ parses product+hazard from titles (`detect_hazard`, config keyword map); `EpantScraper` is the weekly direct cross-check (primary ΕπΑντ coverage is the Δι@ύγεια source with the ΕπΑντ org UID); `RasffAdapter` selects `apitalks` (paid JSON via HttpClient) vs `scrape` per config.
- Registry is now **tier-aware** — Tier-1 adapters get an `HttpClient`, Tier-2 scrapers a `ScrapeClient`. sources.yaml gained ΣτΕ/ΕπΑντ/dpa.gr entries + adapter keys/options for all six (selectors are best-effort defaults to verify against the live pages).
- Fixed a latent Phase-0 bug: `Alerter.fire()` collided with the logger's fixed `source`/`error` columns whenever a caller passed them (the runner + scheduler alert paths did) — now consumed from context.

**Epic 4 (Tier-3 Collection — commercial inbox) — implemented and tested** (FR-3):
- `adapters/inbox.py` — `CommercialInboxAdapter` (tier 3) reads **only the configured shared inbox** (`legal-intel@…`), via an injected `MailboxReader` seam (`ImapMailboxReader` in prod — lazy imaplib, creds from the secret store; fixtures in tests). It refuses to read at all without an explicit `inbox_address` — there is no path to a personal mailbox. It parses each email (HTML links via a stdlib extractor, or bare URLs from plain text), fetches each link's content via the Tier-1 `HttpClient` (best-effort), and yields SourceRecords marked `commercial: true` with the newsletter's editorial in `external_commentary`.
- Sender→source mapping is config (`sender_source_map`); every commercial source is `authority_rank: 3`, so Epic 2's merge guarantees a commercial record never wins metadata over an official Source (covered by a test) while its editorial is preserved.
- Registry gained the `inbox` key (tier-3 → `HttpClient`); `sources.yaml` gained a `Commercial Inbox` source (disabled).

**Epic 5 (Topic Tagging) — implemented and tested** (FR-6, AD-7/8):
- `pipeline/tag.py` — rule-based first: Ontology keyword matching (GR/EN) over title+full text **plus** EuroVoc-descriptor/source-hint → Topic mapping, every result constrained to Ontology `topic_id`s (an unknown keyword or descriptor never creates a Topic). `Topic` gained `eurovoc_descriptors`/`celex_types`; `Item.descriptor_hints` (transient) is populated by normalize from `raw_metadata` (`eurovoc_descriptors`/`topics_hint`).
- LLM **edge-case tagger** (Story 5.2): runs via the `MeteredLLMClient` (stage `topic_tag`) only for Items rule-based tagging leaves untagged, proposals validated against the Ontology before persist (AD-7). Config-gated by `config/tagging.yaml` (`llm_fallback`, optional `model`; the file is optional — safe defaults if absent). The runner passes its `llm` to `tag()`; the phase-0 fake responder returns no topics so the walking skeleton is byte-for-byte unchanged.
- `tagging_coverage(items)` helper for the >90% data-quality target (surfaced later by the Quality Observer).

**Epic 6 (Relevance Triage) — implemented and tested** (FR-7/8/9, AD-2/5/8/13):
- `pipeline/triage.py` — deterministic rules first (KAD match / high-priority topic → A; all-excluded-sector → B; the fired `rule_id` recorded in the `class_reasoning` envelope, `decided_by: rule`), then the LLM classifier for the undecided.
- Classifier now returns the **full structured contract** — `relevance`, `confidence`, Greek `reasoning`, `sector_touchpoints[]`, `action_signal`, `specialist_needed` — captured onto the Item (new fields `sector_touchpoints`/`action_signal`/`specialist_needed`; `action_signal` drives the WF2 24h fast-track later). Confidence threshold is config (`TriageConfig.high_confidence`, from `relevance_rules.yaml` `triage:`); high/low-confidence → A/B, everything else → C.
- `pipeline/retention.py` (Story 6.3, AD-5/AD-2): Class B is index-only; Class C keeps full text under a **config TTL (7 days) → `sweep_overdue()` flags `overdue`**; `promote_class_c_to_a()` **refuses unless full text is present** (AD-2) and `downgrade_class_c_to_b()` purges full text. (Epic 8 wires the Notion review queue onto these.)

**Epic 7 (Interpretation Engine) — implemented and tested** (FR-10/11/12, AD-7/9):
- `pipeline/interpret.py` runs the 7 conceptual steps (legal-type → scope → delta → retrieval → client-impact → actions → confidence, each logged for traceability) as a deterministic retrieval/augmentation step feeding a structured generation; the output **validates against the `Interpretation` schema before persist** (AD-9) — a failure raises `PermanentError` and sets nothing (no partial record); the draft carries the not-legal-advice disclaimer.
- Retrieval augmentation (Story 7.2): `retrieve_related()` pulls 3–5 prior Items with overlapping Topic **and** same authority within 3 years; gold-standard `InterpretationExample`s (optional `config/interpretation_examples.yaml`) are injected as few-shot by Topic; the Client Context Document (optional `config/client_context.md`) grounds the system prompt; cold start proceeds on it alone. The runner passes its `known` Items in for retrieval.
- Model escalation (Story 7.3): `escalation_model` when topic ∈ config `topic_in` **or** the Item is `specialist_needed` (flagged by triage — the fix for the old pre-interpretation check); all model ids from `interpretation_config.yaml`, every call metered.

**Epic 8 (Human Review Workflows & Feedback) — implemented and tested** (FR-13/14/15/18/22, AD-6/11):
- `pipeline/review.py` — the legal team's daily loop as deterministic HUMAN-actor logic: `assign_reviewer` (expertise-first, then least-loaded); **WF1** `relevance_review` (A/B, wrapping the Epic 6 retention promote/downgrade, stamping decision/reviewer/timestamps); **WF2** `approve_interpretation` / `edit_and_approve` (captures the field diff into `review_feedback`) / `reject_and_redo` + `regenerate_after_reject` (re-interprets with the reviewer notes fed back) / `escalate`, plus `wf2_sla` (24h if `action_signal == immediate`, else 3 business days); **WF3** `set_client_action` (+ `track_deadline` reminder via alerting).
- Bidirectional edits + reclassify (Story 8.4, AD-11): `apply_reviewer_edit` validates any status change through the state machine (illegal → raises); `reclassify_b_to_a` re-fetches full text and **hydrates it in place on the existing `page_id` — never mints a new Item even if the hash differs** — then enqueues (or runs) interpretation.
- `agents/quality_observer.py` (Story 8.5) — the weekly `QualityObserver.run(items, ledger)` computes SM-1..SM-7 + tagging-coverage against the spec §9.5 thresholds, fires alerts on breaches, and returns a retro (optional metered Greek narrative). `business_days_between` helper for the SLA metrics.
- New Item Group-4 review fields (reviewer, review timestamps, `review_feedback`, client-action fields, `reclassified_from_b`, metric anchors); `interpret` now stamps `draft_created_at`.

## Run it

`uv` was not installed on the current machine; use the project venv directly (see setup below). With `uv` present, `uv run --extra dev python -m pytest -q` also works.

```bash
.venv/Scripts/python -m pytest -q     # 145 tests, all green
.venv/Scripts/python -m legal_intel   # walking skeleton end-to-end (offline)
```

Expected skeleton run: 4 fake events ingested → **3 Items** (one duplicate merged), one each Class **A** (with a draft interpretation), **B** (index-only, no full text), **C** (ambiguous, held for review), plus a cost-ledger report. Re-running is idempotent.

## Next step

**All 9 epics (0–8) are implemented and tested offline — Environment A is feature-complete.** The full FR set (FR-1..FR-22) has landing code with a green 145-test suite, every stage exercised on fake data with pluggable real backends. What remains is **not new pipeline code** but productionization and the separate Environment B track:

1. **Real-source activation** (per source, gated on the PRD §14 open questions): fill each source's `options` in `config/sources.yaml`, flip `enabled: true`, install the `full` extra, provide secrets in `.env`. Tier-2 selectors and the JS-fetcher (Playwright) need verification against live pages (spec §5.2); real Notion write mapping is stubbed in `NotionApiBackend.write_page` (Story 0.5 provisioning) — wire it before `LEGAL_INTEL_NOTION_BACKEND=notion`.
2. **Ontology workshop** — `config/ontology.yaml` is still a draft placeholder (blocks production tagging quality); all tagging/triage code is data-driven and needs no changes once it's finalized.
3. **Client Context Document** — drop `config/client_context.md` to lift interpretation cold-start quality (§8.7).
4. **Scheduler wiring for real cadences** — `platform/scheduler.py` + `adapters/registry.build_enabled_adapters` are ready; connect APScheduler (`full` extra) and the Quality Observer's weekly job.
5. **Environment B (Cowork agents)** — the 8 on-demand legal-team agents in `cowork-agents.md` are a separate downstream track, not built here. The Env-B data contract (AD-11) fields they consume are all populated on the Item.

See PRD §14/§15 for the open questions + assumptions to confirm with the client before flipping real sources on.

Notes on activation of already-built collection tiers:
- **Tier-2**: the row/link/id selectors in `sources.yaml` are best-effort defaults — verify each against the live page (spec §5.2). JS-heavy sites (ΣτΕ, RASFF scrape mode) need a Playwright-backed fetcher injected into the `ScrapeClient`; the default fetcher is static-HTML httpx.
- **Tier-3 inbox**: set `inbox_address` + IMAP creds (env vars named in options) and enable the `Commercial Inbox` source; it reads only that shared mailbox.

Continue with the BMAD implementation flow (`bmad-sprint-planning` → `bmad-create-story` → `bmad-dev-story`) **if BMAD is installed** on this machine (global at `~/.claude/_bmad`; reinstall v6.10.0 if absent). If BMAD isn't available, just implement directly from `epics.md` — the code is independent of BMAD.

## Prerequisites / setup on a new machine

1. **Python 3.10+** (3.13 works). `uv` is nice-to-have but optional — plain `venv` + `pip` is enough.
2. This folder (cloned or copied).
3. **Recreate the venv** — `.venv/` does not travel between machines (it hard-codes an absolute interpreter path from wherever it was created). On a fresh checkout:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -e ".[dev]"   # offline path; add "[full]" for real connectors
   ```
4. *(Optional)* BMAD reinstalled — only to keep running the workflow skills + `memlog.py`/`lint_spine.py` helpers.
5. **`.env`** from `.env.example` — only when *activating* real connectors (Notion token, Anthropic key, `DATA_GOV_GR_API_KEY`). The offline pipeline + all tests need none — real adapters are exercised in tests via injected fixture HTTP.

## Open questions blocking real connectors (need client input — PRD §14)

1. Notion workspace ownership at MVP — client-provided vs REBORRN-owned?
2. Ontology workshop date — gates production tagging (`config/ontology.yaml` is a draft placeholder).
3. RASFF integration — scrape (free) vs Apitalks (paid)?
4. Current/approved Anthropic model IDs for each stage.
5. Reviewer roster + topic-expertise routing map.
6. Is the Client Context Document available (interpretation cold-start input)?
7. Notification channel for alerts — Slack, email, or both?

*Planning was run in BMAD "Fast path" with `[ASSUMPTION]` tags — see PRD §15 for the assumptions index to confirm.*
