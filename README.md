# Legal Intelligence Collection Layer

Automated legal/regulatory **horizon scanning → relevance triage → interpretation**
for a wholesale tobacco/food + franchised retail food-service business (KAD 46.35,
46.37, 46.38, 56.10, 56.30). This repository is **Environment A** — the Claude Code
production pipeline that runs headless, collects from ~15 Greek/EU sources,
deduplicates and classifies each Legal Event, and drafts a structured interpretation
for the ones that matter. Notion is the single source of truth the legal team works in.

> **Status: Phase 0 ✅ · Epics 1–7 ✅ — the full automated pipeline.** End-to-end
> offline on *fake* data: all three collection tiers (seven Tier-1 adapters + text
> extraction, six politeness-governed Tier-2 scrapers, the Tier-3 commercial
> shared-inbox parser); config-driven weighted dedup with authority-ranked
> identity-preserving merge, supersession, and a human confirmation queue; Ontology
> topic tagging (keywords + EuroVoc) with a metered, Ontology-validated LLM
> fallback; relevance triage into A/B/C (deterministic rules → structured LLM
> classifier) with class-aware retention and a Class C TTL/overdue sweep; and a
> schema-validated interpretation engine with retrieval augmentation, few-shot
> examples, and model escalation. All unit-tested against fixtures — still zero
> network/tokens. Remaining: **Epic 8** (human review workflows + weekly Quality
> Observer). See `_bmad-output/` for the PRD, architecture spine, and epic/story plan.

## Architecture in one line

Pipes-and-filters over a Notion blackboard: each stage is an idempotent filter that
reads Items in one `status` and writes them in the next; the `status` field is the
only coordination pipe. Full contract in
[`_bmad-output/planning-artifacts/architecture/…/ARCHITECTURE-SPINE.md`](_bmad-output/planning-artifacts/architecture/architecture-mouhalis-legal-2026-07-13/ARCHITECTURE-SPINE.md)
(16 architecture decisions, AD-1..AD-16).

```
adapters/  → the only code that talks to the outside world (Tier 1/2/3 sources)
pipeline/  → the filters: normalize → dedup → tag → triage → interpret
agents/    → Claude Agent SDK agents (triage, interpretation, quality observer)
core/      → shared contracts: models, state machine, MeteredLLMClient, NotionGateway, config
platform/  → scheduler, politeness middleware, cost ledger, logging, alerting
config/    → business rules as data (sources, ontology, relevance rules, interpretation)
```

## Quick start (Phase 0)

Runs offline — no Notion token or API key needed (local backend + fake LLM).

```bash
# venv + pip (works everywhere; .venv/ is machine-local — recreate on new checkouts)
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; on POSIX use .venv/bin/python
.venv/Scripts/python -m pytest -q                 # run the test suite (123 tests)
.venv/Scripts/python -m legal_intel               # walking skeleton end-to-end

# or, if uv is installed
uv run --extra dev python -m pytest -q
uv run python -m legal_intel
```

Expected: 4 fake Legal Events ingested → **3 Items** in the store (the cross-source
duplicate is merged), one each of Class **A** (with a draft interpretation), **B**
(index-only, no full text), and **C** (ambiguous, full text held for review), plus a
cost-ledger report. Re-running is idempotent.

## Configuration

Business rules live in `config/*.yaml` and are read at runtime — never hard-coded
(AD-8). Environment variables select backends and hold secrets:

| Variable | Purpose | Default |
|---|---|---|
| `LEGAL_INTEL_NOTION_BACKEND` | `local` (offline) or `notion` | `local` |
| `LEGAL_INTEL_LLM_BACKEND` | `fake` or `anthropic` | `fake` |
| `LEGAL_INTEL_CONFIG` | path to the config dir | `./config` |
| `LEGAL_INTEL_LOCAL_STORE` | JSON file to persist the local store | in-memory |
| `NOTION_TOKEN` / `NOTION_DATABASE_ID` | real Notion (backend=notion) | — |
| `ANTHROPIC_API_KEY` | real Claude (backend=anthropic) | — |

Real integrations (`notion-client`, `anthropic`, `playwright`, …) are lazy-imported
by their backends and ship in the `full` extra: `pip install -e ".[full]"`.

## What's next

Epic 8 (human review workflows + Quality Observer) — the final epic — see
[`_bmad-output/planning-artifacts/epics.md`](_bmad-output/planning-artifacts/epics.md)
and `HANDOFF.md` for the current state and the next step. Continue with the BMAD
implementation flow (`bmad-sprint-planning` → `bmad-create-story` →
`bmad-dev-story`) per story, or implement directly from `epics.md`.

To **activate** a real Tier-1 source: fill its `options:` in `config/sources.yaml`
(org UIDs, dataset, etc.), set `enabled: true`, install the `full` extra
(`pip install -e ".[full]"` for `httpx`/`pdfplumber`), and provide any secrets in
`.env`. The adapters are already wired via `adapters/registry.py`.
