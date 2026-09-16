# SILO — Brazilian fund-industry data, ingested daily and served for accountability

> **Dashboard:** [https://silo-bz.vercel.app/](https://silo-bz.vercel.app/) — rebuilt
> after every nightly ingest; the page header says when.
> **Read API:** [https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/](https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/)
> — schema `api`, anon key, open read.
> **Caller docs:** [https://octo-98895abd.mintlify.site](https://octo-98895abd.mintlify.site)
> (source: [`api-docs/`](api-docs/quickstart.mdx); for agents: [`api-docs/agents.mdx`](api-docs/agents.mdx)).

## What SILO is

SILO keeps a continuous, verifiable record of the Brazilian fund industry — net assets,
flows, delinquency, tranche structure, payout behaviour — assembled every day from the
public filings of **CVM**, **BACEN** and **B3** and stored in one Postgres warehouse
(Supabase). It is built for **financial accountability**: checking a claim against what
was actually filed, whether the reader is a researcher, an agent, or someone opening the
dashboard. It is not built for choosing investments; there is no advice, rating or
recommendation anywhere in it.

Three things read the warehouse: a **read API** (schema `api` over PostgREST, with a
machine-readable catalog so an LLM can discover and query it without a human in the
loop), the **dashboard** (an Evidence.dev site, snapshotted nightly), and a second
Evidence site for listed companies. SILO — this repository — is the part that writes:
fetch, parse, validate, store, and the SQL that turns landing tables into something
worth reading.

What it refuses to do is the point. A failed fetch raises; a field the source did not
publish stays blank; an unknown identifier returns nothing rather than a plausible
number; a partly filed period is withheld until it is complete; an unadjusted price says
so. Concretely, every change is held to five rules (`CLAUDE.md`):

1. **Never fabricate.** No fallback values, no fills, no inferred joins.
2. **Never swallow a failure.** It raises, or it is written to `cvm_ingest_log`.
3. **Provenance from source keys.** Every row keeps its natural key and its original CSV
   row (`raw`); every ingest writes exactly one audit row.
4. **Validate before upsert.** Invalid rows are dropped and counted, never coerced.
5. **Idempotent by construction.** Named UNIQUE keys and `ON CONFLICT … DO UPDATE`; a
   re-run is always safe.

## What it covers

| Source | Family | What is read | Cadence | What it enables |
| --- | --- | --- | --- | --- |
| CVM | **FI** — investment funds | daily NAV and flows (`inf_diario`); portfolio composition and holdings — equities with their B3 ticker, fund-of-fund quotas, debentures with their issuer (`cda`); investor profile (`perfil`); balance sheet (`balancete`) | daily / monthly | AUM, flows, quotaholders, concentration; the fund → ticker → company join |
| CVM | **FIDC** — receivables funds | monthly NAV and delinquency (`tab_IV`); tranches (`tab_X`) and their subscriptions/redemptions; aging buckets 30–1080+ days (`tab_VI`) | monthly | delinquency, subordination, tranche performance against promise |
| CVM | **FII** — real-estate funds | monthly NAV, yield and distributions (`geral`, `ativo_passivo`, `complemento`); property-level detail | monthly / yearly | payout coverage, yield distribution, FII vs FIAGRO |
| CVM | **FIP**, **FIAGRO** | quadrimestral patrimony (FIP); monthly NAV (FIAGRO, published from May 2025) | yearly / monthly | private equity and agribusiness inside the industry totals |
| CVM | **SECURIT** — CRA / CRI / OTS securitisers | monthly emissions; per-series status, rating and yield; cash-flow waterfall; annual statements | monthly / yearly | outstanding by family, defaults, payments by priority, maturity wall |
| CVM | **CIA Aberta** — listed companies | registry; ITR/DFP accounts; IPE events (Fatos Relevantes); FCA tickers | per filing | company financials and events; the only company ↔ ticker link, never name-matched |
| BACEN | SGS, PTAX, Focus | SELIC, CDI, IPCA, IGP-M, INPC, poupança, PIB; PTAX buy/sell per currency; Focus consensus per indicator and horizon | daily / business days | the macro context every fund is measured against |
| B3 | COTAHIST, corporate events | unadjusted OHLC, volume, ticker and ISIN per session; splits, groupings, bonuses and dividends per ISIN | daily (yearly zips for history) | quotes, monthly market and option activity; adjustment factors once verified against the tape |
| B3 | **BDI** — securities lending (incl. trade-by-trade), investor flow, index float, instrument registry | short balance and borrow rates per ticker; buy/sell volume per investor type; free-float share counts and B3 sector; shares outstanding per ticker | daily — **~21 business days of retention, no archive** | the Short Monitor (% of float, days to cover, borrow cost), the investor-flow panel, and — from the trade tape — which brokerage lent and borrowed each name. **Not backfillable**: a session missed is lost, so the daily job is the only way this history exists |
| ANBIMA | class boletim | monthly figures per ANBIMA class and type | monthly | class-level benchmarks, served by `api.anbima_classes` (an ETF-only view is kept for compatibility) |
| Apify scrape | ETF market snapshot | NAV, price, yields, volatility, drawdown per listed ETF | daily, gated on `APIFY_TOKEN` | the market side of the ETF page; self-skips without the token |

Where each dataset lands, at what grain, and what is ingested but not yet served is in
[docs/DATA_INVENTORY.md](docs/DATA_INVENTORY.md). The schema itself is
`src/store/schema.sql` plus the append-only `src/store/migrations/`.

## How it works

### One pipeline, three stages

```
  ┌───── FETCH ─────┐    ┌───── PARSE ────┐    ┌───── STORE ────┐
  │ src/fetchers/   │ →  │ src/parsers/   │ →  │ src/store/     │
  │  cvm_fetcher    │    │  validation    │    │  pg_client.py  │
  │  bacen_fetcher  │    │  (CVM zip→csv  │    │  schema.sql    │
  │                 │    │   and BACEN df │    │                │
  │                 │    │   normalization│    │                │
  │                 │    │   live in the  │    │                │
  │                 │    │   fetchers)    │    │                │
  └─────────────────┘    └────────────────┘    └────────────────┘
                                                       ▲
                           ┌───── ORCHESTRATE ──────────┘
                           │ src/pipeline/
                           │   cvm_pipeline.CVMIngestor
                           │   bacen_pipeline.BacenIngestor
                           │   run_backfill.py  (one-shot, all years)
                           │   run_daily.py     (cron, current month + 7-day window)
                           └─────────────────────────────────────
```

| Package         | Role                                                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/fetchers/` | **FETCH** — HTTP/SDK calls only. CVM downloads ZIP/CSV from `dados.cvm.gov.br` with retry, DNS rotation, and on-disk cache. BACEN wraps `python-bcb`.                          |
| `src/parsers/`  | **PARSE** — shared field/CNPJ/date validation. CVM CSV extraction is co-located with `CVMFetcher.fetch()` because it needs the URL/filename context. BACEN DataFrame normaliza |
| `src/store/`    | **STORE** — psycopg2 Supabase client and chunked upserts; canonical schema.                                                                                                    |
| `src/pipeline/` | **ORCHESTRATE** — wires the three stages, writes audit log rows, runs daily/backfill.                                                                                          |

### The daily cycle

Everything runs in GitHub Actions against Supabase; there is no server to keep up.

1. **06:00 UTC — `daily_ingest.yml`.** Applies the schema and any new migration
   (`psql`, lock-guarded, idempotent), then runs `run_daily`: the current and previous
   month of every monthly CVM dataset plus any month in a trailing four-month window
   with no successful audit row (CVM publishes with a 1–2 month lag; a month not yet
   published is logged `skipped`, not `error`), the last seven sessions of B3 quotes,
   and the BACEN series. Then `ANALYZE`, then the analytical layer is rebuilt, then —
   on a successful scheduled run — the dashboard's deploy hook fires.
2. **08:00 UTC — `watchdog.yml`.** Re-runs any slice whose data stopped advancing, so a
   silent outage heals itself instead of waiting for a person to notice.
3. **`health.yml`.** Reads the audit log and the tables themselves and fails loudly when
   they disagree: no audit row for a run, slices stuck at `running`, an entity whose
   latest month stopped moving, a matview trailing its source, an `api.*` probe that
   answers wrong. A scheduled failure files (or bumps) one tracking issue.
4. **Fills on demand — `backfill.yml`.** One entity and year range at a time,
   serialized, with current coverage printed before anything is written.

### How the data is stored

- **Proper types**: DATE and NUMERIC (not text) for all date and money columns.
- **JSONB audit column**: Every row preserves the original CSV (`raw` field) for re-processing.
- **Partitioning**: `cvm_fi_diario` is partitioned by year (monotonic append, ~5M rows/yr).
- **Indexes**: BRIN on date columns, unique constraints on natural keys (idempotent ON CONFLICT upserts).
- **No soft deletes**: Deletion is physical; canceled funds drop out of `cvm_fund_registry.status`.
- **Partitioned where it is large**: `cvm_fi_diario` (~5M rows a year) is partitioned by
  year, with BRIN indexes on its dates.

## How it is read

### The analytical layer

`src/store/analytical/`, applied by `scripts/apply_analytical.sh` after every ingest, is
the read side: conformed dimensions (`dim_fund` — a materialized view — plus category,
administrator and gestor), the monthly fact matviews (`fact_fund_monthly`,
`fact_security_monthly`), a completeness view that says which months are fully filed
(`mv_period_completeness`, read through `latest_complete_period()`), the suspicious-deal
screens, per-class and ETF performance rankings, and finally schema `api` — the only
surface exposed to callers.

### The read API

Schema `api` is served by Supabase's PostgREST at the URL above: a catalog
(`rpc/catalog`) and a coverage map (`rpc/coverage`) that an agent reads first, a panel
primitive (`api.panel` — one row per id, date, metric and value), and typed functions
for funds, quotes, option chains and search. Row caps live inside the SQL, landing
tables are revoked from `anon`, and `health.yml` asserts both on every run. Signing in
(GitHub OAuth, at [`/signin.html`](https://silo-bz.vercel.app/signin.html)) raises the
caps and the query budget for a token holder. The contract and its edge cases:
[docs/API.md](docs/API.md); how "ingested" became "a researcher pulls a panel":
[docs/planning/SERVING.md](docs/planning/SERVING.md).

### The dashboard

`dashboard/` is an Evidence.dev site: SQL in Markdown, extracted to parquet at build time
and queried in the browser through DuckDB — a **static snapshot, not a live view**. It is
rebuilt after every successful nightly ingest (the deploy hook above) and on every merge
that touches it, and its header shows **Snapshot Built** so nobody has to guess how old
the numbers are.

| Route | Page | What it shows |
| --- | --- | --- |
| `/` | Brazilian Fund Industry Data | entry point: headline figures, freshness signal, reading path |
| `/industry` | Industry Structure | net assets by family and by asset class, quotaholders, new funds, FIP and FIAGRO |
| `/fi` | FI Industry | AUM and flows, daily subscriptions vs redemptions, investor base, allocation by asset type |
| `/fidc` | FIDC Credit Monitor | delinquency, aging, subordination, tranche flows and performance |
| `/fii` | FII Market | FII vs FIAGRO, yield distribution, payout coverage |
| `/fund` | Fund Explorer | per-fund NAV, flows, quotaholders and rebased returns |
| `/performance` | Fund Performance | rankings by class, rebased cumulative return |
| `/etf` | ETF Market | registry by provider and segment, exchange volume, scraped market snapshot |
| `/markets` | B3 Markets | monthly traded volume, instrument mix, option activity |
| `/macro` | Macro Context | SELIC and CDI, inflation, PTAX, Focus consensus |
| `/managers` | Managers | administrator and gestor league tables |
| `/securit` | Securitization | outstanding by family, defaults, payment waterfall, maturity wall |
| `/suspicious` | Suspicious Deal Screens | zombie growth, captive vehicles and the other screens |
| `/dormant` | Dormant Funds | vehicles that file every month and do nothing |
| `/ops` | Pipeline Ops | audit log, freshness per entity, table freshness, when the snapshot was built |

Two rules shape every chart. **Blank is never zero**: a month the source did not publish
renders as a gap, not a dip. And **the axis ends at the last month that has data** —
never the month in progress, never a completeness bound measured on a different filing
(the "Spine rule" in [dashboard/README.md](dashboard/README.md)). Visits are counted by
Vercel Web Analytics.

### The webapp

`webapp/` is a second Evidence site over the CIA Aberta tables: the company registry,
consolidated ITR/DFP financials (revenue, net income, margins, ROE) and the Fato
Relevante feed. The conventions that matter when reading it are in
[webapp/README.md](webapp/README.md).

## Operating it

| Workflow | When | What |
| --- | --- | --- |
| `test.yml` | every PR and push | the offline pytest suite; on dispatch, a read-only `api.*` smoke against production |
| `daily_ingest.yml` | 06:00 UTC, and on dispatch | the daily cycle above. `daily` is the scheduled run, ANALYZE and analytical refresh included; `analytics-only` is just those two; `b3-backfill` loads yearly COTAHIST zips for an exact year range. `rebuild_dashboard=true` also fires the deploy hook after a manual run |
| `watchdog.yml` | 08:00 UTC | self-healing re-run of stale slices |
| `health.yml` | scheduled | the gates above; files an issue on failure |
| `backfill.yml` | on dispatch | historical fills, one entity at a time; `fi_doc_type` repairs one FI source without re-fetching the others |

Secrets: `POSTGRES_URL` (Supabase, `sslmode=require`); `VERCEL_DEPLOY_HOOK_URL` (a deploy
hook of the Vercel project `silo` on `main` — the project in team `deloslabs` whose
public URL is `silo-bz.vercel.app`; the auto alias `silo-deloslabs.vercel.app` is not the
public URL); `APIFY_TOKEN` (optional). The dashboard build reads the
`EVIDENCE_SOURCE__supabase__*` variables set on the Vercel project.

Schema changes are a commit: `src/store/schema.sql` plus a new
`src/store/migrations/NNN_*.sql`; every ingest applies them, with `lock_timeout` and
retries so a blocked `ALTER TABLE` gives up in seconds instead of queueing behind every
reader. Dashboard builds are gated by `scripts/vercel_should_build.sh` — production
always builds, previews only when `dashboard/` changed — because one build is 25–45
minutes of SELECTs against production. Day-to-day upkeep — what to check and how
often, reading `cvm_ingest_log`, healing gaps, the yearly partition rollover, a
symptom → fix index — is [docs/DATABASE_MAINTENANCE.md](docs/DATABASE_MAINTENANCE.md).

## What's next

The pipeline runs unattended; **serving is the open front**. Everything below is an
operator action or a known defect, none of it speculative roadmap. The build-out history
is in [docs/planning/CHANGELOG.md](docs/planning/CHANGELOG.md); the dashboard's ship
checklist in
[docs/planning/SHIP_DASHBOARD_2026-09-14.md](docs/planning/SHIP_DASHBOARD_2026-09-14.md).

### The API is live

```
https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/
```

Schema `api` is applied and exposed, the row caps and landing-table REVOKEs are
in place, and `health.yml` verifies both on every run — the anon probe asserts
`rpc/coverage`, `rpc/catalog`, `quotes` and `funds` answer 200 while
`cvm_fi_diario`, `b3_cotahist`, `cia_account` and `bacen_sgs` under
`Accept-Profile: public` do **not**.

Sign-in is live too: GitHub OAuth, with the page at
`dashboard/static/signin.html`. A user token raises `panel` ids 3 → 50,
`search_funds` 25 → 200, `option_chain` 200 → 2,000 and the query budget
3s → 8s. It does not raise PostgREST's server-wide 1,000-row cap, which is the
same for everyone.

### Known defects

- **`etf_daily` / `etf_latest` can be absent from production.** Migration 06
  recreates them when missing, so a run whose schema step failed leaves them
  gone and the backfill's "Refresh ETF metrics" job then fails on an assertion
  that is really reporting the earlier failure. The ETF dashboard page depends
  on these views.
- **Dashboard builds are slow** (~25 min). The remaining cost is `fi_investor_mix`
  (4m19) and `fi_investor_split` (3m13), which scan `cvm_fi_perfil` across 24 months.
  Optimizing them needs `EXPLAIN ANALYZE` against real data.
- **`cvm_fip_periodic` holds a pre-fix remnant.** Rows stored before the key was
  corrected carry `row_hash = 'pre-migration-34:<id>'` and are the survivors of
  a key that discarded 72–77% of each file. A backfill of `entity=fip` writes
  the real rows alongside them.

### Deferred by design

- **Historical backfills** for `securit` and `fidc` — the daily window only heals the
  trailing months, so deep history for the recently-fixed field maps needs `backfill.yml`.
- **`VERCEL_DEPLOY_HOOK_URL`** — set. Fired after every successful scheduled Daily
  Ingest, and after a manual dispatch that sets `rebuild_dashboard=true`; fills never
  touch Vercel. Must be a deploy hook of the `silo` project on `main`.
- **`APIFY_TOKEN`** — set. The ETF market scrape self-skips without it, and also
  skips (does not fail the daily run) when Apify returns
  `full-permission-actor-not-approved` or HTTP 408 `run-timeout-exceeded`.
  The fetcher starts the actor asynchronously (the sync dataset endpoint caps
  at 300s). Default actor is `apify/playwright-scraper`.
- **Company ↔ ticker** comes from CVM's published FCA valores-mobiliários filing
  (`cia_ticker` → `vw_company_ticker`), never from name matching.
- **Fund → company** now exists as data but is not served. `cvm_fi_cda_acoes.cd_ativo`
  is the published B3 ticker a fund holds, so fund → ticker → `cia_ticker` → company
  is a real join over ingested rows. No `api.*` object exposes it yet, and no edge
  is ever inferred from a name.
- **Prices are not corporate-action adjusted.** `close_unit` (= `close / quotation_factor`,
  both published) makes levels comparable across papers quoted per lot, but a split still
  reads as a jump and `adjusted` is `false` on every row. `b3_corporate_event` holds the
  published events; the adjustment ships once B3's per-label factor convention is verified
  against the tape (`vw_b3_share_count_event`), not before.

## What's intentionally not here

- **No ingest REST API, and no PostgREST dump of landing tables.** The pipeline writes to Supabase via GitHub Actions and the CLI. Callers read schema `api` at `https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/` ([api-docs/quickstart.mdx](api-docs/quickstart.mdx), [docs/API.md](docs/API.md)). `serve/` is the local adapter. The old localhost ingest Flask (`app.py` / `src/api/`) is deleted.
- **No fabricated quotes.** The old `b3_calc_api` (non-B3 domain + hard-coded sample dicts) stays deleted. Historical quotations come from B3's public COTAHIST zips (`src/fetchers/b3_fetcher.py` → `b3_cotahist` → `api.quotes`). An unknown ticker returns an empty result, never a guessed last close — `404` from `serve/`, `200 []` from PostgREST, which has no adapter to shape the error. Same contract, different status code.
- **No local Postgres / Docker / Alembic.** Supabase Postgres is the single source of truth. Use `scripts/seed_local_db.py`
  with a local Postgres for offline testing.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.

## Working on the code

Local setup, the CLI and the tests are documented in `CLAUDE.md` (commands),
[scripts/README.md](scripts/README.md) (operator tooling) and the two Evidence READMEs.
The essentials, folded away:

<details>
<summary>Repository layout</summary>

```text
.
├── src/
│   ├── fetchers/               # HTTP/SDK calls only — no parsing, no storage
│   │   ├── cvm_fetcher.py      # CVMFetcher.fetch(entity, doc_type, year, month)
│   │   ├── cvm_config.py       # URL templates + dataset configs (entity × doc_type matrix)
│   │   ├── bacen_fetcher.py    # BacenClient (SGS/PTAX/Expectativas/TaxaJuros)
│   │   ├── b3_fetcher.py       # public COTAHIST daily/yearly quotation zips
│   │   ├── cia_fetcher.py      # listed-company (CIA Aberta) filings
│   │   └── apify_etf_fetcher.py# ETF market scrape (gated on APIFY_TOKEN)
│   ├── parsers/
│   │   ├── mapping.py          # the declarative FIELD_MAP engine + coercions
│   │   ├── validation.py       # CNPJ / date / numeric / record validators
│   │   └── field_maps/         # per-dataset CSV header → typed DB column
│   ├── store/
│   │   ├── pg_client.py        # get_pg_client(), upsert_rows() — the ONLY DB door
│   │   ├── schema.sql          # canonical schema (tables + audit log)
│   │   ├── migrations/         # NNN_*.sql, append-only — never edit a historical one
│   │   └── analytical/         # 01–19: dims, fact matviews, screens, rankings, schema api
│   ├── pipeline/               # wires fetch→parse→store, writes cvm_ingest_log
│   │   ├── cvm_pipeline.py     # CVMIngestor — the (entity, doc_type) orchestrator
│   │   ├── bacen_pipeline.py   # BacenIngestor
│   │   ├── b3_pipeline.py      # B3Ingestor (COTAHIST)
│   │   ├── anbima_pipeline.py  # ANBIMA boletim
│   │   ├── ingest_<entity>.py  # per-entity ingest_* methods (fi, fidc, fii, securit, cia…)
│   │   ├── run_daily.py        # CLI: incremental daily update
│   │   └── run_backfill.py     # CLI: full historical backfill
├── serve/                      # read-only local adapter over schema api
│   ├── app.py                  # `python -m serve.app` — 127.0.0.1:8080, NOT an ingest trigger
│   ├── pool.py                 # one pooled client per process
│   └── catalog.py              # machine-readable metric catalog (CATALOG_VERSION)
├── dashboard/                  # Evidence.dev analytics dashboard
│   ├── pages/                  # Markdown-based pages + embedded SQL queries
│   ├── sources/
│   │   └── supabase/           # Supabase Postgres connection config
│   └── README.md               # Dashboard-specific setup
├── webapp/                     # Evidence.dev CIA Aberta (listed-company) analytics
│   ├── pages/                  # Listed-company financials & events
│   └── README.md               # Webapp-specific setup
├── tests/                      # offline pytest suite (DB + HTTP mocked)
├── scripts/                    # operator + dev tooling — see scripts/README.md
│   ├── apply_analytical.sh     # build the analytical layer (01–19) after ingest
│   ├── verify_pipeline.py      # quality gate against live Supabase
│   ├── seed_local_db.py        # offline: real CVM data → local DuckDB
│   ├── vercel_should_build.sh  # Vercel ignoreCommand (0 SKIPS, 1 BUILDS)
│   └── queries/                # 13 numbered read-only SQL files
├── docs/                       # prose docs (NOT published; see .mintignore)
│   ├── API.md                  # the read contract, and the Supabase-native decision
│   ├── DATABASE_MAINTENANCE.md # upkeep runbook: checks, cadence, partition rollover
│   ├── DATA_MODELING.md        # read before adding a new CLASS of data
│   ├── ETF_AND_PERFORMANCE.md  # why etf_daily is empty post-CVM-175
│   ├── supabase_operations.md  # connection / pooler / ops notes
│   └── planning/
│       ├── CHANGELOG.md        # workstream history
│       └── SERVING.md          # ingested → researcher pulls a panel (steps 0–7)
├── api-docs/                   # PUBLISHED Mintlify pages (quickstart + reference)
├── index.mdx                   # published docs landing page
├── docs.json                   # Mintlify config: theme + navigation
├── .mintignore                 # keeps Evidence template markdown out of the MDX parser
├── vercel.json                 # dashboard build config + ignoreCommand
├── .githooks/                  # pre-commit: blocks credentialed URLs, bad syntax
├── apify/                      # ETF market scrape actor (gated on APIFY_TOKEN)
├── .github/
│   ├── actions/apply-schema/   # composite action: schema + migrations, lock-guarded
│   └── workflows/
│       ├── test.yml            # pytest on PR/push; api-smoke on dispatch
│       ├── daily_ingest.yml    # cron @ 06:00 UTC + workflow_dispatch
│       ├── watchdog.yml        # cron @ 08:00 UTC — self-healing staleness re-run
│       └── backfill.yml        # on-demand full historical backfill
├── requirements.txt
└── .env.example
```

</details>

<details>
<summary>Quick start (local)</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/install_hooks.sh   # fail-safe pre-commit guards (secrets, syntax)
cp .env.example .env   # fill in POSTGRES_URL (Supabase connection string)

# 1. Apply schema + migrations (one-time, against your Supabase Postgres)
python scripts/apply_schema.py

# 2. Run an incremental update
python -m src.pipeline.run_daily

# 3. Run a one-shot historical backfill (e.g. 2019 onward)
python -m src.pipeline.run_backfill --start-year 2019

# 3c. Optional: B3 COTAHIST yearly quotation zips (large; daily run already
#     picks up the last 7 calendar days)
python -m src.pipeline.run_backfill --b3-only --b3-start-year 2019

# 3b. Build the analytical layer (views/functions) — AFTER data is ingested
bash scripts/apply_analytical.sh

# 4. Verify the pipeline (local DuckDB, ~2 min, skips FI inf_diario)
python scripts/seed_local_db.py --skip-fi
python scripts/run_analysis_local.py

# 5. Verify against live Supabase DB
python scripts/verify_pipeline.py
```

</details>

<details>
<summary>Partial fills from the CLI</summary>

Ingest is GitHub Actions plus the pipeline CLI. There is no localhost HTTP
control plane. One entity or year:

```bash
python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2024 --end-year 2024
python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2019

# Repair only the months missing from one FI document's table (not the audit log)
python -m src.pipeline.run_backfill --cvm-only --entity fi --doc-type balancete --repair-gaps
python -m src.pipeline.run_daily
```

One month of one dataset — call the ingestor method (needs `POSTGRES_URL`):

```python
import asyncio
from src.pipeline.cvm_pipeline import CVMIngestor

asyncio.run(CVMIngestor().ingest_fidc_tranche(2024, 5))
```

Failed fetches raise and write `cvm_ingest_log`; they are not auto-retried.
Re-run the same command. Quality gate: `python scripts/verify_pipeline.py`.

The read-only HTTP adapter is separate: `python -m serve.app` (see
[docs/API.md](docs/API.md)).

</details>

<details>
<summary>Tests</summary>

```bash
PYTHONPATH=. pytest tests/ -v
```

All tests are offline (Supabase DB and HTTP are mocked). The read API is covered by
`tests/test_serve_api.py` — also fully offline; Postgres is stubbed.

CI: `.github/workflows/test.yml` runs this suite on every PR and push to `main`
(pip cache + `.pytest_cache`). **Actions → Tests → Run workflow** also runs a
read-only `api.*` smoke against Silo (`POSTGRES_URL`); SQL errors fail, zero
rows do not.

</details>
