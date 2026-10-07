# AGENTS.md

This file is the source of truth for every agent that works in this repository:
Claude Code, Codex and Cursor. It holds the data-integrity rules, the owner's
rules, the architecture and the commands. `CLAUDE.md` only imports it and adds
Claude Code's own mechanics. Add or change a rule here, nowhere else.

The four-page model of the system is `docs/architecture/` (`SYSTEM.md`,
`DATA_FLOW.md`, `OPERATIONS.md`, `DECISIONS.md`). Where every doc lives: `docs/README.md`. Load the SILO skill before
changing ingest, schema `api`, `serve/`, or panel/catalog:
`.claude/skills/silo/SKILL.md`.

Keep this file under 32 KiB. Codex truncates project instructions at that size by
default (`project_doc_max_bytes`), so anything past it would be a rule Codex never
sees. Long per-dataset notes belong in `docs/agents/dataset-notes.md`.

## Agent skills

### Issue tracker

GitHub Issues via `gh`. See `docs/agents/issue-tracker.md`. Before a batch of
issues, confirm every label exists and create one issue first (that file says how).
The `tech-debt` skill runs the audit → issues → phase PR loop.

### Triage labels

Use the five defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

## Infrastructure facts

- One Vercel project (`silo-bz`, team `deloslabs`) exists, and it builds only
  `dashboard/`: root `vercel.json` hardcodes `cd dashboard`. It also disables
  git-triggered production deployments on `main`, so a merge publishes nothing:
  only the deploy hook does, fired by a scheduled daily run whose analytical apply
  succeeded (a red source does not block it) or by a dispatch with `rebuild_dashboard=true`. `scripts/vercel_should_build.sh`
  builds a PR preview only when `dashboard/`, `vercel.json` or the script itself
  changed. `webapp/` has no Vercel deployment (`webapp/README.md`). Do not assume
  a second project.
- Canonical clone: `~/Dev/SILO-BZ`, remote `github.com/PedroDnT/SILO-BZ`. Before
  starting work, run `git remote -v && pwd` to confirm you are in it (or in one of
  its worktrees), not a stale copy.

## Tooling

### Data and deploy access

- Supabase: use the Supabase MCP, project ref `zcjbtpxuhdekpwcxmepn`. Run read-only
  SELECTs freely, but ask before running any DDL or data-modifying SQL.
- Vercel: use the Vercel MCP. Project `silo-bz` in team `deloslabs` builds only
  `dashboard/` (see Infrastructure facts), so don't call list_projects to rediscover it.

## Planning register

The register of open work is `docs/planning/OPEN_ITEMS.md` (index:
`docs/planning/README.md`).

### Register workflow

When fixing register items: first list the open items with a one-line plan each, and
check for existing branches or PRs for each item and merge them rather than redoing
the work. Then fix them one at a time: make the change, verify it, and mark its status
in the register before moving to the next. Keep exploration for any single item short;
do not survey the whole codebase, Supabase and Vercel before the first fix. Commit one
fix per item, or add a blocker note. When a step only the owner can do is required
(e.g., creating a DB role), record it clearly and move to the next item. Do not end a
session after exploration alone. The `fix-register` skill runs this loop.

## Working style

### Before asking design questions

Check the current code, `docs/adr/`, `docs/planning/`, and the planning register
before asking the owner a design or hosting question. If the answer is already in
the code or recorded decisions, state what you found and ask only about the
remaining ambiguity.

### Discovery is not prioritization (owner's rule)

An agent may discover problems, but discovering one does not make it the
current work. An agent may report a newly discovered issue and suggest opening
a ticket. Unless the owner explicitly authorizes it, an agent must not start
implementing the discovered work, raise it to active priority, or widen the
current task to include it.

## The shape of the system: 4 infra, 4 products

Reach for this before reporting a problem — it decides whose problem it is, and
symptoms routinely surface one layer away from their cause.

**Infrastructure** (four, and only four):

|                    | Runs                                                              | Fails as                                        |
| ------------------ | ----------------------------------------------------------------- | ----------------------------------------------- |
| **GitHub Actions** | ingestion + parse (`run_daily`, `run_backfill`, health, watchdog) | a red run, a slice in `cvm_ingest_log`          |
| **Supabase**       | the Postgres store                                                | disk pressure, a failing query, a missing grant |
| **Vercel**         | hosting for `dashboard/` only; `webapp/` is not deployed          | a build error, a stale or mis-pointed domain    |
| **Cloudflare**     | the portfolio-diagnosis demo: a Worker, the engine Container, private R2 for traces, an LLM provider (`deploy/cloudflare/`) | a Worker error, a Container timeout, a missing secret, an LLM refusal |

**Products** (what anyone actually consumes):

|                     | Is                      | Contract                                         |
| ------------------- | ----------------------- | ------------------------------------------------ |
| **the API**         | schema `api` + `serve/` | `docs/reference/API.md`, `api.catalog()`, `api.coverage()` |
| **the dashboard**   | the Evidence sites      | parquet built at deploy time                     |
| **the stored data** | the warehouse itself    | the integrity rules below                        |
| **the diagnosis**   | `src/portfolio/` (statement readers, engine, report, investigator) behind the Cloudflare Worker | `docs/reference/portfolio/`, ADR 0001 (stateless), ADR 0003 (traces in R2) |

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
for apps is schema `api` plus `serve/` (`docs/reference/API.md`). Serving roadmap (catalog →
SQL smoke → pool → honest returns → lookup → privileges → HTTPS) is
`docs/planning/SERVING.md`. Operators trigger ingest with GitHub Actions or
`python -m src.pipeline.run_daily` / `run_backfill` (optional `--entity`).

> Read `docs/architecture/` for the four-page model of the system (`SYSTEM.md`,
> `DATA_FLOW.md`, `OPERATIONS.md`, `DECISIONS.md`), `README.md` for what SILO is
> and what it covers (operator commands are folded at
> its end and in `scripts/README.md`), `docs/reference/DATABASE_MAINTENANCE.md` for the
> ongoing DB upkeep runbook (checks, cadence, audit-log triage, partition rollover,
> troubleshooting), and `docs/planning/CHANGELOG.md` for the
> workstream history. A previous version had multiple FastAPI
> services + a Solana "Delos Oracle" + a `b3_calc_api`; all were removed. Do not
> reintroduce Docker/Alembic, local Postgres-as-source-of-truth, or a **fake** B3
> quote API — see "What's intentionally not here" in `README.md`. Public COTAHIST
> zips are in scope (`b3_cotahist`). The user-facing read API is schema `api` +
> `serve/` (`docs/reference/API.md`); do not expose landing tables or reintroduce an ingest HTTP API.

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
   fails validation is dropped and counted — never coerced into a guess. One normalisation is
   allowed: `mapping.coerce("cnpj")` strips punctuation and zero-pads to 14 digits, which restores
   the leading zero a CSV export drops. Measured 2026-10-02: every fund, class, company, FIDC and
   FII identity CNPJ already has 14 digits, so it pads nothing there. A column that can hold a
   CPF too (manager, originator, auditor) is typed `text`, never `cnpj`: padding an 11-digit CPF
   would fabricate a CNPJ.
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
  `pg_client.upsert_rows(client, table, rows, conflict_columns=)` (chunked at 500 by
  default, `CVM_UPSERT_CHUNK_SIZE` overrides it and CI sets 5000; `ON CONFLICT DO
UPDATE`). **Never open a raw DB connection elsewhere — always go through `pg_client`.**
  `schema.sql` is the canonical schema; `migrations/NNN_*.sql` are append-only.
- **`src/pipeline/`** — `cvm_pipeline.CVMIngestor`, `bacen_pipeline.BacenIngestor`, and
  `b3_pipeline.B3Ingestor` wire the stages and write audit-log rows. `ingest_<entity>.py`
  modules hold the per-entity `ingest_*` methods. CLI entry points: `run_daily.py` (cron:
  current month + 7-day window, including B3 COTAHIST daily zips) and `run_backfill.py`
  (one-shot, all years; B3 yearly zips are `--include-b3` / `--b3-only`).
- **`serve/`** — read-only Flask adapter over schema `api` (`python -m serve.app`).
  Not an ingest trigger. See `docs/reference/API.md`.

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

The other per-dataset notes (storage layout, FII versions, the FNET register,
restatement diffs, lineage, the analytical layer) are in
`docs/agents/dataset-notes.md`. Read that file before you touch those tables.

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
`docs/reference/DATA_MODELING.md` first: extend the existing `dim_`/`fact_` star schema and model
time series as a **long fact** keyed on `(instrument natural key, date[, metric])` rather
than a wide per-source table — same provenance + idempotent-upsert rules apply.

The daily run probes a **gap-aware trailing window** for monthly datasets
(`CVM_DAILY_LOOKBACK_MONTHS`, default 4): it always refreshes the current + previous month
and additionally re-fetches any month in the window with no successful `cvm_ingest_log`
row, so a slice CVM publishes late (its 1–2 month lag) is healed on the next run instead of
missed forever. A not-yet-published month 404s and is logged `skipped`, not `error`. Deep
history is still `run_backfill`'s job, not the daily window's.

### Adding an API endpoint

Every capped function **refuses** above one 1,000-row page (`22023`, with a why/how
message built by `assert_row_cap`) — none trims silently. A new endpoint also needs a
catalog entry, a regenerated `openapi.json` (`scripts/gen_openapi.py`) and a regenerated
MCP contract (`scripts/gen_mcp_contract.py` + a `t()` line in
`supabase/functions/silo-mcp/tools.ts`); `tests/test_mcp_contract.py` fails until all
three agree. A new or changed signature also regenerates the SDK's
`sdk/silo_client/contract.json` (`scripts/gen_sdk_contract.py`), which `SiloClient.rpc()`
checks calls against; `tests/test_sdk_rpc.py` fails while it is stale.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12
pip install -r requirements-dev.txt  # requirements.txt (the ingest's) + what only the tests import
bash scripts/install_hooks.sh        # installs .githooks (pre-commit: secrets, syntax)
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

`pytest.ini` sets `pythonpath = .` and `asyncio_mode = auto`. There is no git pre-push hook:
`.githooks/` holds only `pre-commit`, which blocks committing Postgres URLs with credentials
and Python that fails `py_compile`. The offline suite runs in `test.yml` on every pull
request.

**Every branch carries its own docs.** Before pushing, add the branch's changelog row
as its own file, `docs/planning/changelog.d/<date>_<branch with / as ->.md`, holding
just the row (or a `No-changelog: <reason>` commit trailer); never edit
`CHANGELOG.md`'s table directly, because every open PR then conflicts on it and
GitHub ignores `merge=union` (#587). Keep every row main already had word for word,
in a fragment, in `CHANGELOG.md` or in its archive `docs/archive/changelog/`
(`scripts/roll_changelog.py` folds the fragments into the table and rolls old rows
out, on a branch of its own; or a `Changelog-removes: <reason>` trailer), and update `README.md`, the planning index and `OPEN_ITEMS.md` where the
branch made them stale. A change to the files one of the four `docs/architecture/`
pages describes edits that page in place, short and with no dated entry (or a
`No-architecture-change: <reason>` trailer). The `pytest` job in `test.yml` runs the row comparison on
every pull request, which also covers merges made in GitHub's web UI: one dropped
#324's and #325's rows from main via #322. PRs auto-merge on green. Claude Code is
held to this by hooks (`CLAUDE.md`); Cursor and Codex are not hooked, so do it by
hand.

**Open pull requests ready for review, never as drafts** (owner's rule). PRs here
merge by auto-merge once CI is green, and a draft blocks that until someone marks it
ready by hand. This overrides any tool or harness default that opens drafts.
One exception: the scheduled agents in `.claude/agents/` (Scout, Builder) open
drafts on purpose, because agent output must never auto-merge without the owner's
review (`docs/planning/AGENTS.md`). Only the owner marks an `agent:*` PR ready.

## Database (Supabase)

- Never run unbounded queries on large tables (e.g. `cvm_fi_diario`, `cia_account`,
  `b3_lending_trade`, `cvm_fi_cda_acoes`). Always add a `LIMIT` or a filtered `WHERE`;
  prefer `pg_class.reltuples` over a bare `COUNT(*)`, and filter any `COUNT(*)`.
- For bulk rewrites (e.g. re-keying), work in batches and check the row count after each batch.
- Before any destructive change (trim, delete, re-key), stop and confirm the plan with the owner.

## Times are UTC-3 (owner's rule)

This rule changes how times are **shown**, never how they are computed or stored.
Reference every time in UTC-3: Brasília, `America/Sao_Paulo`. Brazil has had no
daylight saving since 2019. This covers replies, reports, PR bodies, comments and new doc text.
Convert what a source reports in UTC before quoting it: GitHub Actions schedules and run
times, Supabase logs, `timestamptz` output. Where someone has to match the time
against that source, add the UTC value in parentheses: the daily run starts at
03:00 UTC-3 (06:00 UTC).

Never change anything that runs in order to follow it. That means:

- cron expressions;
- the workflows' `TZ: America/Sao_Paulo`, which dates B3 sessions;
- `AT TIME ZONE` in SQL;
- the database time zone;
- `timestamptz` columns and stored values;
- date keys;
- anything the API returns.

Existing docs and CHANGELOG rows are not rewritten either.

## Environment

- Never run `npm install` from the home directory. `cd` into `dashboard/` or `webapp/`
  first (the repo root has no `package.json`) and confirm that is the intended target.
- On macOS, `date` is BSD date. Use `gdate`, or write tests that are portable across
  GNU and BSD `date`.

## Consumers (read-only, query Supabase directly)

Both are **Evidence.dev** projects (Node-based: `npm install && npm run sources && npm run dev`
→ localhost:3000; `npm run build` → `build/`). They connect to the same Supabase Postgres via
`@evidence-dev/postgres` and only read — never write.

- **`dashboard/`** — fund **and market** analytics at
  [https://silo-bz-deloslabs.vercel.app/](https://silo-bz-deloslabs.vercel.app/), 19
  pages. Industry and backdrop: Overview (`/`), Industry Structure (`/industry`),
  Macro Context (`/macro`), Rates and Curves (`/rates`), B3 Markets (`/markets`),
  Short Monitor (`/short`), Follow the Money (`/flows`). By asset class: FI (`/fi`), FIDC Credit Monitor
  (`/fidc`), FII Market (`/fii`), Securitization (`/securit`), ETF (`/etf`).
  Granular: Managers (`/managers`), Fund Explorer (`/fund`), Fund Holdings
  (`/holdings`), Performance (`/performance`), Suspicious Screens (`/suspicious`), Dormant Funds (`/dormant`).
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
  (`mode=daily|analytics-only|b3-backfill|b3-cash-dividends`). It bootstraps the schema
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
  `https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp` (one tool per `t()`
  line in `tools.ts`, `verify_jwt` off). Like analytical SQL, a merge does not redeploy
  it. Apply analytics first, then dispatch `deploy_mcp.yml` (needs the
  `SUPABASE_ACCESS_TOKEN` secret; it checks the live `tools/list` against `tools.ts`),
  or run `supabase functions deploy silo-mcp --project-ref zcjbtpxuhdekpwcxmepn --no-verify-jwt`
  locally; never `supabase config push`.

Schema rollout = commit `schema.sql` + a new `migrations/NNN_*.sql`, then either let CI apply it
or run `scripts/apply_schema.py` against Supabase. Idempotent via `CREATE TABLE IF NOT EXISTS` +
named UNIQUE constraints. Note CI applies schema with `psql -v ON_ERROR_STOP=1` (parses SQL
comments correctly), so author migrations to be psql-clean.

## Cursor Cloud specific instructions

### Environment layout

- Python **3.12** in a virtualenv at `.venv/` (gitignored, persisted in the VM snapshot).
  The startup update script (`python3 -m venv .venv` + `pip install -r requirements-dev.txt`)
  keeps it fresh. Run Python via `.venv/bin/python` (or
  `source .venv/bin/activate`); there is no global install of the project deps.
- If `.venv/bin/pip` is missing, the snapshot venv is empty. Recreate it:
  `sudo apt-get install -y python3.12-venv && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- `duckdb` is required by the offline verification scripts but is used only for local dev;
  it is listed in `requirements.txt` under "Local dev / offline verification".
- Git hooks live in `.githooks/` (enabled with `bash scripts/install_hooks.sh`, which sets
  `core.hooksPath`). Only a `pre-commit` hook exists (secret scan + `py_compile`/`bash -n`);
  there is no git pre-push hook.
- Claude Code's hooks do not run for Cursor or Codex. The "Every branch carries its
  own docs" rule under "Commands" is yours to follow by hand before every push.

There is **no ingest Flask**. Do not run `flask --app app` or revive `app.py` /
`src/api/`. Ingest is GitHub Actions plus:

```bash
.venv/bin/python -m src.pipeline.run_daily
.venv/bin/python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2024 --end-year 2024
```

### What runs without credentials (default dev/testing loop)

No `POSTGRES_URL` / Supabase credentials are needed for the core loop:

- Lint/syntax gate: `.venv/bin/python -m py_compile <changed .py files>` (what the
  pre-commit hook runs). There is no ruff/flake8/black configured.
- Tests: `.venv/bin/python -m pytest tests/ -q` — fully offline (DB + HTTP mocked).
- End-to-end pipeline (fetch→parse→store) against **real CVM data over the network** into a
  local DuckDB file: `.venv/bin/python scripts/seed_local_db.py --skip-fi` then
  `.venv/bin/python scripts/run_analysis_local.py`. This is the self-contained way to prove
  the pipeline works. Note: it downloads from the (slow) `dados.cvm.gov.br` server, so
  `--skip-fi` realistically takes ~10–15 min here (the README's "~2 min" is optimistic).
  It writes `.local_db/iliquid_local.duckdb` (~100 MB) — do not commit that file.

### What needs secrets (not runnable in a fresh VM by default)

- The live pipeline (`python -m src.pipeline.run_daily` / `run_backfill`), `scripts/apply_schema.py`,
  and `scripts/verify_pipeline.py` require `POSTGRES_URL` (Supabase Postgres, `sslmode=require`)
  via `.env` (copy from `.env.example`).
- Read API: `.venv/bin/python -m serve.app` (binds `127.0.0.1:8080`). Needs `POSTGRES_URL`
  or `SILO_API_DATABASE_URL`. This is not an ingest trigger.
- The `dashboard/` and `webapp/` Evidence.dev apps (`npm install && npm run sources &&
npm run dev`) are read-only consumers that need a populated Supabase to render data.
- `etf_market_snapshot` ingestion self-skips unless `APIFY_TOKEN` is set.

## Working beside other agents

Codex, Claude Code sessions, the B7 agents and the orchestrator write to this repo at
the same time and do not see each other's sessions. GitHub is the one place they all
see, so it is the lock (owner decision, 2026-10-07, #711):

1. **Claim before you write.** Assign the issue, then comment one line that ends the
   claim: `Claimed by: <agent> · branch <branch>` (`codex`, `claude`, `orchestrator`).
   Every agent posts as the owner's account, so this line is the only way to tell who
   claimed. Work with no issue opens a small one first.
2. **Look for overlap first.** Compare the files you will touch with the changed files
   of every open PR (`GET /repos/{o}/{r}/pulls/{n}/files`). On an overlap, wait or pick
   other work; do not race it to a merge conflict.
3. **Branch prefix names the agent:** `claude/`, `codex/`, `orchestrator/`, `agent/`
   (B7 Routines), `research/`, `demo/`.
4. GitHub is REST only from Claude Code sessions (`gh api repos/...`; GraphQL is 403).

## Codex task-boundary board

- This repository uses the opt-in Codex task-boundary board in `.codex/coordination/project.yaml`.
- Before substantial writes, load the installed `codex-coordinator` skill, list active claims from the primary worktree, and publish only this task's bounded claim.
- The local board is Codex's own; also claim on GitHub as "Working beside other agents" says, so other agents see the claim.
- Native Codex tasks remain the execution, messaging, and transcript authority; an explicitly requested goal Coordinator is on demand, with no heartbeat or mandatory pull-request workflow.
- Reject cross-project notices and never store transcripts, reasoning, prompts, or tool output in Coordinator state.
