# Activation & Operations Runbook

How to access, run, and go live with the Legal Intelligence Collection Layer
(Environment A). For architecture and current build status see `README.md` and
`HANDOFF.md`.

- **Repo:** https://github.com/REBORRNVibes/mouhalis-legal-intel (private)
- **Notion workspace:** "Mouhalis Legal Intelligence" (Legal Events, Cost Ledger,
  Interpretation Examples + WF1/WF2/WF3 views)

---

## 1. Two ways to "access" the system

There is **no separate app to log into** — access is by role:

| You are… | You access via… | What you do |
|---|---|---|
| **Legal reviewer / PM (day-to-day)** | **Notion** — the "Mouhalis Legal Intelligence" page | Work the WF1/WF2/WF3 queues: classify, approve/edit interpretations, set client actions. This is the whole UX. |
| **Operator / developer** | **The GitHub repo + the host** it runs on | Configure sources, deploy, watch logs/cost/alerts. Not needed for daily use. |

The pipeline itself is a **headless background service** — it has no screen; it
reads sources and writes into the Notion databases on a schedule.

## 2. Run it now (offline demo — no tokens, no network)

```bash
git clone https://github.com/REBORRNVibes/mouhalis-legal-intel.git
cd mouhalis-legal-intel
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # Windows
.venv/Scripts/python -m pytest -q        # 154 tests, all green
.venv/Scripts/python -m legal_intel      # one full pass on fake data → console report
```

This proves the whole pipeline end-to-end (collect → dedup → tag → triage →
interpret → persist) with zero configuration. Nothing leaves the machine.

## 3. Configure for real backends

```bash
cp .env.example .env      # then edit .env
.venv/Scripts/python -m pip install -e ".[full]"   # httpx, pdfplumber, playwright, notion-client, anthropic, apscheduler
```

Set in `.env` (loaded automatically):
- `LEGAL_INTEL_NOTION_BACKEND=notion` + `NOTION_TOKEN` + `NOTION_DATABASE_ID`
  (the Legal Events DB). **Share the Notion integration on the page** first.
- `LEGAL_INTEL_LLM_BACKEND=anthropic` + `ANTHROPIC_API_KEY`.
- IMAP creds only if the commercial inbox source is enabled.

## 4. Turn on real sources

Sources ship **disabled**. Per source, in `config/sources.yaml`: fill its
`options`, set `enabled: true`. Recommended order (most→least reliable):
1. **Tier-1 APIs** (EUR-Lex, Διαύγεια, …) — most stable.
2. **Tier-2 scrapers** — verify each site's CSS selectors against the live page
   first; JS-heavy sites (ΣτΕ, RASFF scrape) need a Playwright fetcher.
3. **Tier-3 inbox** — once the shared mailbox is forwarding.

Before relying on it, run in **shadow** (point `NOTION_DATABASE_ID` at a staging
DB) for a few days to check volume and dedup.

## 5. Initiate a run

**One pass, on demand** (this is also what the scheduler calls):

```bash
.venv/Scripts/python -m legal_intel
```

It runs every enabled source once and upserts results into Notion. It is
**idempotent** — safe to re-run; duplicates are merged by key (AD-14).

**On a cadence (production).** The command is stateless per run, so schedule it
with any timer — simplest first:
- **Windows Task Scheduler / cron / systemd timer** → run `python -m legal_intel`
  every N hours. Robust, no extra code. *(Recommended to start.)*
- **APScheduler** (in the `full` extra) via `platform/scheduler.py` for an
  in-process resident scheduler that reads each source's `cadence`.

Add a **weekly** job for the Quality Observer (health metrics + retro):
`agents/quality_observer.py`.

## 6. Operate & monitor

- **Structured logs** — every stage emits JSON log lines (stdout) → ship to your
  log store.
- **Cost Ledger** — one row per LLM call; the monthly report alerts at 2× the
  baseline and on a >5% failed-call rate.
- **Alerts** — scraper breakage (zero rows), circuit-breaker trips, SLA/overdue
  breaches, cost spikes. MVP dispatches to the console; wire the dispatcher in
  `platform/alerting.py` to Slack/email for production.
- **Quality Observer** — weekly SM-1..SM-7 metrics vs thresholds.

## 7. Still to do before full production (config/ops, not code)

- Client **ontology workshop** → finalize `config/ontology.yaml`.
- Drop in `config/client_context.md` (interpretation cold-start).
- Real **source credentials** + Tier-2 selector verification (PRD §14 open Qs).
- Choose **hosting** (data-residency) and wire the alert channel.
- **Environment B** (Cowork agents) — a separate downstream track.
