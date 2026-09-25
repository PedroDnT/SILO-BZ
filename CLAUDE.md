# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent skills

### Issue tracker

GitHub Issues via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

## The shape of the system: 3 infra, 3 products

Reach for this before reporting a problem — it decides whose problem it is, and
symptoms routinely surface one layer away from their cause.

**Infrastructure** (three, and only three):

|                    | Runs                                                              | Fails as                                        |
| ------------------ | ----------------------------------------------------------------- | ----------------------------------------------- |
| **GitHub Actions** | ingestion + parse (`run_daily`, `run_backfill`, health, watchdog) | a red run, a slice in `cvm_ingest_log`          |
| **Supabase**       | the Postgres store                                                | disk pressure, a failing query, a missing grant |
| **Vercel**         | hosting for `dashboard/` and `webapp/`                            | a build error, a stale or mis-pointed domain    |

**Products** (what anyone actually consumes):

|                     | Is                      | Contract                                         |
| ------------------- | ----------------------- | ------------------------------------------------ |
| **the API**         | schema `api` + `serve/` | `docs/API.md`, `api.catalog()`, `api.coverage()` |
| **the dashboard**   | the Evidence sites      | parquet built at deploy time                     |
| **the stored data** | the warehouse itself    | the integrity rules above                        |

Two consequences worth stating, both learned the expensive way:

1. **Diagnose at the right layer.** A dashboard showing no data has at least
   four possible causes across three layers — the data never landed (GitHub),
   the analytical view is stale or wrong (Supabase), the build read a fine
   database but the domain serves an older deployment (Vercel), or the page
   is guarding correctly against a source that is genuinely empty. Row counts
   in a build log and pixels on the public URL are different observations;
   on 2026-09-16 they disagreed, and only the second was true for users.
2. **Do not confuse OUR health with the SOURCE's.** `landed_at` says the
   pipeline ran and succeeded — that is ours to fix. `complete_through` says
   how much CVM has published — that is Brazil's filing calendar, not an
   outage. Gating red/green on the second is how DB Health taught itself to
   cry wolf.

## What this is

Headless ingestion pipeline for Brazilian public financial data, built for **financial
accountability** across three populations: **funds** (NAV, delinquency, tranche
performance, structural health), **listed companies** (ITR/DFP statements, events, the
published ticker map), and **markets** (the B3 tape, the securities-lending book,
investor-type flows, BACEN macro). It downloads, parses, validates, and upserts data
from **CVM** (fund disclosures:
FI, FIDC, FII, FIP, FIAGRO, SECURIT, plus listed-company CIA filings), **BACEN** (SGS
time series including the 26-code IPCA set behind `api.inflation`, PTAX, Focus
expectativas), **IBGE** (SIDRA tables 1419/7060, the IPCA item tree with weights →
`ibge_ipca_item_monthly`, served by `api.inflation_items`), and **B3** (public
COTAHIST quotation zips → `b3_cotahist`) into a **Supabase Postgres** database via
psycopg2. BACEN's IPCA group codes 1640–1643 are Comunicação / Saúde / Despesas
pessoais / Educação — measured against SIDRA, not IBGE's order; never reorder them
by intuition.

There is **no public ingest API** and no localhost ingest HTTP server. Downstream
dashboards (`dashboard/`, `webapp/`) query Supabase directly. The **read contract**
for apps is schema `api` plus `serve/` (`docs/API.md`). Serving roadmap (catalog →
SQL smoke → pool → honest returns → lookup → privileges → HTTPS) is
`docs/planning/SERVING.md`. Operators trigger ingest with GitHub Actions or
`python -m src.pipeline.run_daily` / `run_backfill` (optional `--entity`).

> Read `README.md` for what SILO is and how it works (operator commands are folded at
> its end and in `scripts/README.md`), `docs/DATABASE_MAINTENANCE.md` for the
> ongoing DB upkeep runbook (checks, cadence, audit-log triage, partition rollover,
> troubleshooting), and `docs/planning/CHANGELOG.md` for the
> workstream history. A previous version had multiple FastAPI
> services + a Solana "Delos Oracle" + a `b3_calc_api`; all were removed. Do not
> reintroduce Docker/Alembic, local Postgres-as-source-of-truth, or a **fake** B3
> quote API — see "What's intentionally not here" in `README.md`. Public COTAHIST
> zips are in scope (`b3_cotahist`). The user-facing read API is schema `api` +
> `serve/` (`docs/API.md`); do not expose landing tables or reintroduce an ingest HTTP API.

## Data integrity rules (NON-NEGOTIABLE)

These are the only way to truly break this codebase — fake data silently corrupts every
downstream metric. This list is authoritative:

1. **Never fabricate data.** A failed fetch must `raise` — never return a plausible-looking
   fallback dict (this is exactly why `b3_calc_api` was deleted). Mocks live in `tests/` only.
2. **No silent `except: pass`** around network/DB calls. Failures must `raise` or
   be written to `cvm_ingest_log` — never swallowed.
3. **Preserve provenance.** Every row carries its natural keys (e.g. `cnpj` / `cnpj_securit`
   and `dt_comptc` / `period` / `data_referencia` / `reference_date`, depending on the table)
   directly from source — never synthesize them. Every ingest writes exactly one
   `cvm_ingest_log` row.
4. **Validate before upsert.** All records pass `DataValidator` (`src/parsers/validation.py`):
   CNPJ = 14 digits, dates must parse, NAV/PL non-negative or explicitly nullable. A row that
   fails validation is dropped and counted — never coerced into a guess.
5. **Idempotent by construction.** Every table has a named UNIQUE constraint on its natural
   key; upserts use `ON CONFLICT ... DO UPDATE`. Never plain `INSERT`.

If a change makes `scripts/verify_pipeline.py` fail, the change is wrong — not the
verifier.

## Architecture

Three stages, orchestrated per `(entity, doc_type)` pair:

```
FETCH (src/fetchers/) → PARSE (src/parsers/) → STORE (src/store/)
                         ↑ ORCHESTRATE (src/pipeline/)
```

- **`src/fetchers/`** — HTTP/SDK calls only. `cvm_fetcher.CVMFetcher.fetch(entity, doc_type,
year, month)` is the single entry point; downloads ZIP/CSV from `dados.cvm.gov.br` with
  retry, DNS rotation, and on-disk cache (`CVM_CACHE_DIR`). `bacen_fetcher.BacenClient` wraps
  `python-bcb`. `cia_fetcher` handles listed-company filings. `b3_fetcher.B3CotahistFetcher`
  downloads public COTAHIST zips from `bvmf.bmfbovespa.com.br`. `cvm_config.py` holds the
  `DatasetConfig` matrix (URL template, csv_name_pattern, periodicity, encoding).
- **`src/parsers/`** — `validation.DataValidator` (shared CNPJ/date/numeric validators) and
  `field_maps/<entity>_<doctype>.py` (each exposes one `FIELD_MAP: dict[str,str]`, CSV header
  → DB column). CSV extraction is co-located with the fetcher because it needs URL/filename
  context.
- **`src/store/`** — `pg_client.get_pg_client()` (one psycopg2 connection per run) and
  `pg_client.upsert_rows(table, rows, conflict_cols)` (chunked at 1000, `ON CONFLICT DO
UPDATE`). **Never open a raw DB connection elsewhere — always go through `pg_client`.**
  `schema.sql` is the canonical schema; `migrations/NNN_*.sql` are append-only.
- **`src/pipeline/`** — `cvm_pipeline.CVMIngestor`, `bacen_pipeline.BacenIngestor`, and
  `b3_pipeline.B3Ingestor` wire the stages and write audit-log rows. `ingest_<entity>.py`
  modules hold the per-entity `ingest_*` methods. CLI entry points: `run_daily.py` (cron:
  current month + 7-day window, including B3 COTAHIST daily zips) and `run_backfill.py`
  (one-shot, all years; B3 yearly zips are `--include-b3` / `--b3-only`).
- **`serve/`** — read-only Flask adapter over schema `api` (`python -m serve.app`).
  Not an ingest trigger. See `docs/API.md`.

Storage layout: ~30 tables named `cvm_<entity>_<doctype>` or `bacen_<series>` (plus the
`cia_*` and ETF tables and the `cvm_ingest_log` audit table). Trust `src/store/schema.sql`

- `migrations/` + `src/pipeline/` (`CVMIngestor.daily_update` / `backfill`) as the source
  of truth, not the README's CSV table.
  Wired ingest datasets include `cvm_fidc_tranche`, `cvm_fidc_aging`, `cvm_fidc_cedente` /
  `cvm_fidc_sacado` / `cvm_fidc_setor` / `cvm_fidc_scr` (FIDC informe tabs I, VIII, II, X —
  named originators, anonymized top-25 debtors, sector, SCR ladder; migration 38, with
  per-tab first months in `_FIDC_TAB_FIRST_PERIOD`; served by `api.fidc_cedentes` /
  `fidc_sacados` / `fidc_portfolio` and the panel metrics `receivables`, `sacado_top1`,
  `sacado_top25`), `cvm_fidc_garantia` (tab `X_7`, guarantees on the credit rights as a
  value and a %, as filed — the denominator is undocumented, so never call it
  "coverage"; migration 45, key `(cnpj, period)`, first month 2019-11), `cvm_securit_serie`,
  `cvm_securit_fluxo`, `cvm_fi_balancete`, `cvm_cia_*`, `cvm_etf_registry`,
  `cvm_fi_cda_acoes`, `cvm_fi_cda_cotas` and `cvm_fi_cda_debentures` (fund holdings —
  CDA blocks 4, 2 and 6, members of the archive `cda` already downloads. Block 4
  carries `cd_ativo`, the B3 ticker, so it is the join between the fund universe and
  the quote tape; block 2 carries the held fund's CNPJ and CVM's published
  `emissor_ligado` flag; block 6 carries `cpf_cnpj_emissor`, the debenture issuer's
  own CNPJ, which joins to `cia_*` with no bridge. Block 6 has no `CD_ATIVO`, so its
  key ends in `row_hash` after (fund, month, issuer, maturity) — see migration 35 for
  the audit. Blocks 3, 5, 7 and 8 are not ingested),
  `anbima_class_monthly` (every ANBIMA class/type; `anbima_etf_class_monthly`
  survives as an ETF-only compat view), `etf_market_snapshot` (scraped ETF NAV/cotistas — wired
  into the daily run but **gated on the `APIFY_TOKEN` secret**; it self-skips when the
  token is unset. See `docs/ETF_AND_PERFORMANCE.md`), and `b3_cotahist` (B3 COTAHIST
  quotes; daily run fetches the last 7 calendar days, yearly backfill is opt-in.
  Serve cash quotes from `vw_b3_quote_vista` (`tpmerc = '010'`), not the option-heavy parent),
  and the **B3 BDI** group — `b3_lending_open_position`, `b3_lending_rate`,
  `b3_investor_participation`, `b3_investor_participation_monthly`,
  `b3_index_portfolio`, `b3_instrument_registry`, `b3_lending_trade` (securities lending
  including the trade-by-trade tape with the brokerage on each leg, investor-type
  flow, index free float and the cash instrument registry; `src/fetchers/b3_bdi_fetcher.py`
  carries the verified endpoint contract).

**FII filings keep every version** (migration 43): `versao` is part of the key of
`cvm_fii_mensal` and `cvm_fii_periodic` (`UNIQUE NULLS NOT DISTINCT`), so a restatement
lands beside the original instead of overwriting it. Read the current filing through
`vw_fii_mensal_latest` / `vw_fii_periodic_latest`, never by picking a version yourself.

**The FNET register** (`fnet_document`, `fnet_document_filter`; migration 42,
`src/fetchers/fnet_fetcher.py` → `src/pipeline/fnet_pipeline.py`, audit entity `fnet`) is
B3 Fundos.NET's document list: metadata only, one row per FNET id, and every version is a
new id with `versao` and `modalidade` (AP original, RE voluntary restatement, RC
CVM-required). It is the only public record of FIDC restatements — CVM's FIDC CSVs carry
no version. FNET rows carry **no CNPJ**: a document's fund is a `cnpjFundo` row in
`fnet_document_filter` (the CNPJ we queried with) or it is unknown — never inferred from
`fund_name`. The daily run crawls the last 3 delivery days (day windows; a month-wide
query times out) and sweeps a rotating 1/14 of the FII/FIDC registry; history is
`backfill.yml` with `fnet_start` / `fnet_end` (one year per dispatch) and `fnet_sweep`.
Served by `api.fund_documents` / `api.fund_restatements` (analytical file 24).

**Lineage.** `cvm_ingest_log` carries `git_sha` (from `GITHUB_SHA`, NULL when unset —
never guessed) and `parser_version` (`PARSER_VERSION` in `src/pipeline/ingest_log.py`;
bump it only when a parser or field map changes what a stored value means).
`api.coverage()` exposes `landed_git_sha`, the commit of the run that set `landed_at`.

**The BDI group is a ratchet, and the only part of this warehouse that is.** B3 keeps
~21 business days of those tables and publishes no archive, and an over-wide request
returns HTTP 200 with a silently clamped window — so a missed session is lost at any
price, `run_backfill` deliberately offers no lending option, and every ingest reconciles
the sessions it received against the ones it asked for. Read `b3_lending_open_position`
through `is_total` (B3 publishes both the per-market rows and its own `Total` sum; adding
them double-counts), and read `% of float` together with `float_basis`
(`index_free_float` and `shares_outstanding` are different denominators). In
`b3_lending_trade`, `doador`/`tomador` are BROKERAGES, not beneficial owners —
~75% of trades carry the same code on both legs, so a large borrow through a
broker is its client book, not its own position.

The **analytical layer** (`src/store/analytical/`, applied by `scripts/apply_analytical.sh`
after ingest) is the read side the dashboards query: `dim_fund` (a **materialized view**,
refreshed daily by cron + the apply re-create) plus `dim_fund_category` / `dim_administrator`
/ `dim_gestor`; the `fact_fund_monthly` / `fact_security_monthly` matviews; the
`fraud_screen_*` suspicious-deal screens (15; served to API callers only as the
`api.screen_*` wrappers in 23 — the public functions hold no client grant); and the `fund_performance_*` / `etf_*` ranking
functions (16–17). ETFs are carved out of the fund universe and ranked separately —
`etf_daily` is empty for post-CVM-175 share classes (see the ETF doc).
`mv_savings_flow_monthly` / `api.mv_savings_flow_monthly` (18) is reproduced as-found so
CASCADE recreates of `fact_fund_monthly` cannot destroy it; nothing in this repo reads it.
Schema `api` is 19 (the contract, `catalog()` / `coverage()`, `api.assert_row_cap`),
20–21 (short interest, lending participants), 23 (screens) and 24 (FNET). Every capped
function **refuses** above one 1,000-row page (`22023`, with a why/how message built by
`assert_row_cap`) — none trims silently. A new endpoint also needs a catalog entry, a
regenerated `openapi.json` (`scripts/gen_openapi.py`) and a regenerated MCP contract
(`scripts/gen_mcp_contract.py` + a `t()` line in `supabase/functions/silo-mcp/tools.ts`);
`tests/test_mcp_contract.py` fails until all three agree.

### Adding a dataset (the `(entity, doc_type)` matrix)

Touch these in order:

1. `src/fetchers/cvm_config.py` — add a `DatasetConfig`.
2. `src/parsers/field_maps/<entity>_<doctype>.py` — add the `FIELD_MAP`.
3. `src/store/schema.sql` **and** a new `src/store/migrations/NNN_*.sql` — add the table
   (never edit historical migrations; keep `schema.sql` in sync).
4. `src/pipeline/ingest_<entity>.py` — add the `ingest_*` method.
5. Wire the method into `CVMIngestor.daily_update` / `backfill` (and `run_daily` /
   `run_backfill` if it is a new source). Skip this and GitHub Actions never fetches it.
6. `tests/` — add an offline test with a CSV fixture (skip this and CI won't protect it).

Periodicity: **monthly** datasets (`fi`, `fidc *`, `fiagro mensal`) take `(year, month)` and
key on `competencia` = first day of the month; **yearly** datasets (`fii *`, `fip`,
`securit *`) take `(year)` only; **BACEN** time series key on `(series_code, date)`.

For a _new class_ of data (e.g. market/price series for securities), read
`docs/DATA_MODELING.md` first: extend the existing `dim_`/`fact_` star schema and model
time series as a **long fact** keyed on `(instrument natural key, date[, metric])` rather
than a wide per-source table — same provenance + idempotent-upsert rules apply.

The daily run probes a **gap-aware trailing window** for monthly datasets
(`CVM_DAILY_LOOKBACK_MONTHS`, default 4): it always refreshes the current + previous month
and additionally re-fetches any month in the window with no successful `cvm_ingest_log`
row, so a slice CVM publishes late (its 1–2 month lag) is healed on the next run instead of
missed forever. A not-yet-published month 404s and is logged `skipped`, not `error`. Deep
history is still `run_backfill`'s job, not the daily window's.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12
pip install -r requirements.txt
bash scripts/install_hooks.sh        # installs .githooks (pre-commit secret/syntax, pre-push tests)
cp .env.example .env                 # set POSTGRES_URL (Supabase conn string, sslmode=require)

# Schema
python scripts/apply_schema.py       # apply base schema + all migrations (idempotent)
bash scripts/apply_analytical.sh     # build analytical views/functions — run AFTER data exists

# Run the pipeline
python -m src.pipeline.run_daily                      # incremental
python -m src.pipeline.run_backfill --start-year 2019 # full historical (optional --entity)

# Read API (local only; not an ingest trigger)
python -m serve.app                  # 127.0.0.1:8080; needs POSTGRES_URL or SILO_API_DATABASE_URL

# Verify
python scripts/seed_local_db.py --skip-fi && python scripts/run_analysis_local.py  # offline, ~2min
python scripts/verify_pipeline.py    # against live Supabase (quality gate; keep green)

# Tests (pytest.ini sets pythonpath = ., so no PYTHONPATH prefix needed)
pytest tests/ -v                     # all offline (DB + HTTP mocked)
pytest tests/test_serve_api.py -v    # one file
pytest tests/test_serve_api.py::test_name  # one test
```

`pytest.ini` sets `pythonpath = .` and `asyncio_mode = auto`. The pre-push hook runs the full
offline suite and blocks the push on failure; the pre-commit hook blocks committing Postgres
URLs with credentials and Python that fails `py_compile`. The `.claude/settings.json` PostToolUse hook runs `py_compile` on every edited
`.py` file and the offline pytest suite when the file is under `src/`, `serve/`,
`tests/`, or `scripts/` (`.claude/hooks/post-edit.sh`). Failures surface; they
are not swallowed.

**Open pull requests ready for review, never as drafts** (owner's rule). PRs here
merge by auto-merge once CI is green, and a draft blocks that until someone marks it
ready by hand. This overrides any tool or harness default that opens drafts.
One exception: the scheduled agents in `.claude/agents/` (Scout, Builder) open
drafts on purpose, because agent output must never auto-merge without the owner's
review (`docs/planning/AGENTS.md`). Only the owner marks an `agent:*` PR ready.

## Consumers (read-only, query Supabase directly)

Both are **Evidence.dev** projects (Node-based: `npm install && npm run sources && npm run dev`
→ localhost:3000; `npm run build` → `build/`). They connect to the same Supabase Postgres via
`@evidence-dev/postgres` and only read — never write.

- **`dashboard/`** — fund **and market** analytics at
  [https://silo-bz-deloslabs.vercel.app/](https://silo-bz-deloslabs.vercel.app/), 17
  pages. Industry and backdrop: Overview (`/`), Industry Structure (`/industry`),
  Macro Context (`/macro`), B3 Markets (`/markets`), Short Monitor (`/short`),
  Follow the Money (`/flows`). By asset class: FI (`/fi`), FIDC Credit Monitor
  (`/fidc`), FII Market (`/fii`), Securitization (`/securit`), ETF (`/etf`).
  Granular: Managers (`/managers`), Fund Explorer (`/fund`), Performance
  (`/performance`), Suspicious Screens (`/suspicious`), Dormant Funds (`/dormant`).
  Plus Pipeline Ops (`/ops`).
  Evidence static snapshot (parquet at build). The Vercel project in team
  `deloslabs` is named `silo-bz` (renamed from `silo` on 2026-09-17, so older
  planning docs and changelog rows still say `silo`); that is the
  GitHub/deploy-hook name, not the public URL. Also buildable as a static site
  for any static host.
- **`webapp/`** — Evidence.dev instance for CIA Aberta (listed-company) analytics over the
  `cia_*` tables: Overview (`/`), Financials (`/financials`, consolidated ITR/DFP with
  margins/ROE), Events (`/events`, IPE + Fato Relevante feed). Mind the data conventions
  in `webapp/README.md` (accented `ÚLTIMO`, net income conta 3.11 **only** — no 3.09
  fallback anywhere, because 3.09 is pre-statutory-participations profit, not net
  income, and banks do generally file 3.11; equity by name). `setor` is the partition
  key for peer comparisons — `/growth` ranks within sector for that reason.

## Deploy

Ingestion target: **GitHub Actions cron → Supabase Postgres** (SILO). Required GitHub
secret: `POSTGRES_URL`. No container registry or Docker. The read-only dashboard is
[https://silo-bz-deloslabs.vercel.app/](https://silo-bz-deloslabs.vercel.app/) (Vercel
project `silo-bz` in team `deloslabs`; any static host also works).

- `.github/workflows/daily_ingest.yml` — 06:00 UTC daily (`run_daily`) + `workflow_dispatch`
  (`mode=daily|analytics-only|b3-backfill`). It bootstraps the schema
  via `psql` on every run, then `ANALYZE`s the tables.
- `.github/workflows/backfill.yml` — on-demand, entity/year-selectable backfill. FI years and
  other entity jobs use `max-parallel: 1`, inspect coverage first, and are gated on a
  one-time `apply-schema` job. `fi_doc_type` can repair one FI source (for example
  `balancete`) without re-fetching the others. Default to one entity; `all` is deliberately
  expensive. `fnet_start` / `fnet_end` / `fnet_sweep` make an FNET-only dispatch (every
  other job skips).
- **A merge deploys nothing to the database.** Analytical SQL (and so schema `api`) goes
  live on the next 06:00 run, or at once via `daily_ingest` `mode=analytics-only`
  (`rebuild_dashboard=true` also republishes the site). The dashboard build's preflight
  refuses to build while a view it reads is missing, so a PR that adds a view its pages
  use fails its Vercel preview until the migration is applied — expected, not a bug.
- `supabase/functions/silo-mcp/` — the read-only remote MCP (Supabase Edge Function, public
  anon key only), live since 2026-09-25 at
  `https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp` (49 tools, `verify_jwt`
  off). Like analytical SQL, a merge does not redeploy it. Deploy with
  `supabase functions deploy silo-mcp --project-ref zcjbtpxuhdekpwcxmepn --no-verify-jwt`;
  never `supabase config push`.

Schema rollout = commit `schema.sql` + a new `migrations/NNN_*.sql`, then either let CI apply it
or run `scripts/apply_schema.py` against Supabase. Idempotent via `CREATE TABLE IF NOT EXISTS` +
named UNIQUE constraints. Note CI applies schema with `psql -v ON_ERROR_STOP=1` (parses SQL
comments correctly), so author migrations to be psql-clean.
