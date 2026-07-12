# Legal Intelligence Collection Layer

Automated legal/regulatory **horizon scanning → relevance triage → interpretation**
for a wholesale tobacco/food + franchised retail food-service business (KAD 46.35,
46.37, 46.38, 56.10, 56.30). This repository is **Environment A** — the Claude Code
production pipeline that runs headless, collects from ~15 Greek/EU sources,
deduplicates and classifies each Legal Event, and drafts a structured interpretation
for the ones that matter. Notion is the single source of truth the legal team works in.

> **Status: Phase 0 — walking skeleton.** The full flow runs end-to-end on *fake*
> data with an offline Notion backend and a fake LLM, proving the architecture before
> real connectors are built. See `_bmad-output/` for the PRD, architecture spine, and
> the epic/story breakdown that drive the build.

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
# with uv (recommended)
uv run --extra dev python -m pytest -q      # run the test suite
uv run python -m legal_intel                # run the walking skeleton end-to-end

# or with pip
pip install -e ".[dev]"
python -m pytest -q
python -m legal_intel
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

Epic 1 (Tier-1 adapters) onward — see
[`_bmad-output/planning-artifacts/epics.md`](_bmad-output/planning-artifacts/epics.md).
Continue with the BMAD implementation flow (`bmad-sprint-planning` →
`bmad-create-story` → `bmad-dev-story`) per story.
