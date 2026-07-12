# PRD Addendum — Legal Intelligence Collection Layer
*Technical depth, options-considered, and mechanism detail deliberately kept out of `prd.md`. Consumed by the Architecture step. Source of record for the detail here is `instructions.md` (v2.0) + `cowork-agents.md` (v1.0) in the project root — this addendum summarizes and cross-references rather than duplicating.*

## A. Storage architecture — options considered

| | Path A (external DB) | **Path B (Notion-first) — CHOSEN** |
|---|---|---|
| Flow | Sources → Staging DB → Normalized DB → Notion sync | Sources → ingestion workers → in-memory dedup/normalize → Notion |
| Pros | Analytics, versioning, backup, scales indefinitely | Single system, no DB ops, immediate legal-team UX, fastest MVP |
| Cons | Extra infra, DevOps overhead | Slower complex queries, Notion rate limits, ~50k-page ceiling, versioning needs extra work |
| Decision | Deferred (adopt >50k items or heavy analytics) | MVP target |

**Migration path (A adoption later):** export full Notion → PostgreSQL via Notion API, retaining IDs to preserve backlinks. See spec §3.1.

## B. Source integration matrix (mechanism detail → spec §5)

**Tier 1 (structured):**
- EUR-Lex / CELLAR — SPARQL (`publications.europa.eu/webapi/rdf/sparql`) + REST by CELEX + Atom feed. No auth. <5 concurrent, 60s query timeout, LIMIT/OFFSET pagination. EuroVoc descriptors as pre-filter. Corrigenda = distinct CELEX suffixes → `supersedes`. Covers CJEU case-law (resource-type JUDG/ORDER/OPIN_JUR).
- Βουλή — `hellenicparliament.gr/api.ashx` JSON/XML, no auth. Early-warning source.
- Δι@ύγεια — `diavgeia.gov.gr/opendata` JSON, no auth. **Most critical** — indirectly covers ΕπΑντ, ΑΑΔΕ, ΕΦΕΤ, ΑΠΔΠΧ, all ministries. PDF text extraction + OCR needed. Key: organization UIDs must be verified.
- EDPB — 2× RSS (news, documents). PDF extraction.
- EFSA — RSS (all/consultations/scientific-outputs) + OpenFoodTox API. Forward-looking.
- GDPRhub — MediaWiki API (`gdprhub.eu/api.php`). English summaries of EU DPA decisions; `recentchanges` for monitoring.
- data.gov.gr — REST, **free API key required**. Secondary/ESG enrichment.

**Tier 2 (scraping, Playwright/requests):**
- Εθνικό Τυπογραφείο (ΦΕΚ) — `search.et.gr`, 2×/day. Selectors must be verified (site modernization pending). Fallback: kodiko.gr, taxheaven.gr.
- ΣτΕ — `adjustice.gr` / `gov.gr` unified νομολογία search. JS-heavy, anonymized. Daily.
- ΕπΑντ — **prefer Δι@ύγεια authority filter**; direct scrape weekly as cross-check.
- ΕΦΕΤ — recalls + announcements, every 4h (time-sensitive). Parse title for product + hazard.
- RASFF — Option A Apitalks REST (paid, low-effort), Option B Playwright (Angular), Option C EFSA feed (indirect/free). Every 4h.
- dpa.gr — e-newsletter parse (primary) + Δι@ύγεια (secondary) + HTML scrape (fallback). HTML, not PDF. Weekly + daily Δι@ύγεια.

**Tier 3 (commercial, shared inbox):** dikaio.ai, Qualex, NB Daily, Lawspot, Lawnet, kodiko.gr, taxheaven.gr, forin.gr, law-firm newsletters. Intake via `legal-intel@client-domain` (BCC forward preferred; never personal mailbox). Parser (IMAP/n8n/Zapier/custom Python) extracts links → fetch → mark commercial. Cross-validation + safety net only.

## C. Deduplication — signal weights (→ spec §3.3)

| Signal | Weight |
|---|---|
| Exact `source_id` match | 1.0 |
| SHA-256 normalized text hash | 0.95 |
| Title Levenshtein > 0.85 | 0.6 |
| Same authority + publication date | 0.5 |
| Topic + entity overlap > 70% | 0.3 |

Thresholds: ≥0.95 auto-merge; 0.70–0.94 human confirm; <0.70 distinct.
Authority hierarchy (merge winner): official primary → official aggregators (kodiko.gr, ΝΣΚ) → commercial aggregators → newsletter/commentary. Keep `additional_sources[]`, `external_commentary`. Idempotency on `source_id + source_name`.

## D. Interpretation pipeline (→ spec §8)

7 steps: legal-type ID → scope → delta → retrieval augmentation → client-specific impact → action extraction → confidence self-assessment. Each a distinct LLM call for quality + traceability. Config in `interpretation_config.yaml` (default vs escalation model, escalation triggers, temperature 0.2, max_tokens ~4000). Full JSON output schema in spec §8.2. Cold start: Client Context Document only (months 0-3), then growing approved-interpretation corpus (RAG + few-shot bank), style converges by month 6+.

**Model IDs:** the spec names specific IDs (e.g. sonnet/opus variants) — treat as **placeholders**; resolve against current availability at build time. Escalation model for csrd_scope, epant_decision, ste_decision, or `requires_specialist_review`.

## E. Notion schema (→ spec §10) — for Architecture to formalize

Main DB **Legal Intelligence**, class-aware property groups: G1 always-populated (title, source_id, source, type, authority, jurisdiction, dates, topics, content_class, class_reasoning, confidence, url, collected_at); G2 full-text (A+C only: full text child page, language, snippet); G3 interpretation (A only: summary, before/after/delta, business lines, support functions, impacts, obligations, actions child page, dates, cited articles, related events relation, specialist flags, confidence notes); G4 review workflow (status, reviewer, review timestamps, notes, client action status, action owner/deadline, reclassify flag). 8 views (Recent, Pending Relevance Review, Pending Interpretation Review, Approved & Actionable, By Topic, Critical Deadlines, Index Archive, My Queue). Aux DBs: Reviewers Workload, Ontology Reference, Interpretation Examples. Sync: batch ≤100, 3 req/s, >2000 chars → child page, >100KB → attachment.

## F. Ontology & relevance rules (→ spec §4, §7)

`ontology.yaml` topic shape: topic_id, name_gr/en, domain, keywords_gr/en, celex_types, eurovoc_descriptors, authorities, priority. Draft topic list spans horizontal/data-protection/ESG/food/franchise-competition/tobacco/retail. **Client-validated in 90-min workshop before production tagging.**
`relevance_rules.yaml` (changes more often than ontology): explicit include (high-priority topic hit, authority+sector, KAD direct mention 46.35/46.37/46.38/56.10/56.30) → Class A; explicit exclude (unrelated sectors, personnel appointments, boilerplate procedural) → Class B.

## G. Scheduling cadences (→ spec §6)

EUR-Lex Atom 30m · Δι@ύγεια 6h · Βουλή daily 08:00 · EDPB/EFSA daily 09:00 · GDPRhub daily 10:00 · ΦΕΚ 2×/day (10:00,18:00) · ΕΦΕΤ/RASFF every 4h · ΣτΕ daily 22:00 · ΕπΑντ daily via Δι@ύγεια · dpa.gr weekly+newsletter · commercial real-time inbox trigger.

## H. Suggested tech stack (indicative → spec Appendix B) — Architecture to ratify/override

Orchestration: Prefect (alt Airflow/n8n) · Ingestion: Python async httpx (alt Node) · Scraping: Playwright · Staging DB (Path A only): PostgreSQL 16 · Text extraction: Apache Tika (alt pdfplumber/unstructured) · LLM: Claude via Agent SDK (tagging/classifier/interpretation default; Opus-class escalation) · Retrieval: pgvector (Path A) / keyword (Path B MVP) · Notion: Notion API Python SDK · Monitoring: Grafana+Prometheus (alt Datadog) · Secrets: Vault (alt AWS SM).

**Path B MVP simplification:** for scaffolding, an in-process scheduler + local file/JSON staging + Notion is sufficient; heavyweight infra (Prefect/Postgres/Grafana) is deferred. Architecture step to decide the minimal Phase-0 stack.

## I. Cowork agents (Environment B) — fields the pipeline must persist (→ cowork-agents.md)

Eight agents read the same Notion. Environment A must guarantee: `class_reasoning`, `confidence_score`, `additional_sources[]`, `external_commentary`, precedent relations, and a B→A re-fetch entry point. Build order for B (later track): Explain Classification → Similar Cases → Reclassify → Weekly Digest → Client Comms Draft → Deep Dive → Policy Update → Ontology Refinement. Prerequisite: 100-200 Items in Notion.

## J. Operational hardening (→ spec §12)

Rate limiting (1 req/5s/domain + ±30% jitter, non-identifying UA, robots.txt, circuit breaker 3×429/503→30min pause, backoff 2/4/8/16/32s, max 1 concurrent/domain). Error handling (transient retry ≤5; permanent alert+skip; selector breakage auto-alert). Data-quality checks (empty-field %, topic-coverage %, dedup spike). GDPR self-compliance (legitimate interest, minimal personal data, deletion process). Cost optimization levers (Haiku for tagging, cache classifier, batch tagging, skip Opus, prompt compression, truncate >20k-token docs).
