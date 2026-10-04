# SILO: Brazilian public financial data, ingested daily and served to people and AI agents

SILO is a production system. A GitHub Actions cron pulls the day's filings from **CVM**, **BACEN**, **IBGE** and **B3**, validates them, upserts them into one Supabase Postgres warehouse, rebuilds the analytical layer and republishes the public dashboard. It keeps a verifiable record of **funds**, **listed companies** and **markets**, for researchers, AI agents and anyone checking a claim against what was actually filed.

It is built for financial accountability, not for choosing investments: there is no advice, rating or recommendation anywhere in it. A failed fetch raises, a field the source did not publish stays blank, and an unknown identifier returns nothing rather than a plausible number.

| Start here  | Link                                                                                                                                  |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Dashboard   | [silo-bz-deloslabs.vercel.app](https://silo-bz-deloslabs.vercel.app/) (rebuilt after every nightly ingest; the page header says when) |
| Read API    | `https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/` (schema `api`, anon key, open read)                                               |
| Caller docs | [`scalar/`](scalar/) — researcher-facing guides on Scalar; `api-docs/` is the operator archive                                        |
| For agents  | [`skill.md`](skill.md), [`llms.txt`](llms.txt)                                                                                        |

## The five rules

Every change is held to these (`AGENTS.md`) by the offline test suite.

1. **Never fabricate.** No fallback values, no fills, no inferred joins.
2. **Never swallow a failure.** It raises, or it is written to `cvm_ingest_log`.
3. **Provenance from source keys.** Every row keeps its natural key and its original CSV row (`raw`); every ingest writes exactly one audit row.
4. **Validate before upsert.** Invalid rows are dropped and counted, never coerced.
5. **Idempotent by construction.** Named UNIQUE keys and `ON CONFLICT ... DO UPDATE`; a re-run is always safe.

## What it covers

| Population                        | Source             | Data                                                                                                                           | Frequency                                                                     |
| --------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| Funds: FI                         | CVM                | daily NAV and flows, holdings (equities by B3 ticker, fund quotas, debentures), investor profile, balance sheet                | daily / monthly                                                               |
| Funds: FIDC                       | CVM                | NAV, delinquency, tranches, aging, originators, debtors, sector, guarantees                                                    | monthly                                                                       |
| Funds: FII, FIP, FIAGRO           | CVM                | NAV, yield, distributions, property detail (every FII filed version kept)                                                      | monthly / yearly                                                              |
| Securitisation (CRA, CRI, OTS)    | CVM                | emissions, per-series status and rating, cash-flow waterfall                                                                   | monthly / yearly                                                              |
| Listed companies                  | CVM                | registry, ITR/DFP accounts, IPE events (Fatos Relevantes), FCA tickers                                                         | per filing                                                                    |
| Market tape                       | B3                 | COTAHIST quotes, corporate events, fixed income ETF prints, daily levels of nine indices (IBOV from 1968, `api.index_history`) | daily                                                                         |
| Securities lending and flows      | B3 BDI             | short balance, borrow rates, trade tape, investor-type flow, index float, instrument registry                                  | daily, **not backfillable** (about 21 business days of retention, no archive) |
| Rate curves                       | B3                 | DI1 futures and the PRE, DOC and DPL reference curves                                                                          | daily                                                                         |
| Macro                             | BACEN, IBGE        | SGS series (SELIC, CDI, IPCA, IGP-M), PTAX, Focus; IPCA item tree (SIDRA)                                                      | daily / monthly                                                               |
| Global backdrop                   | Treasury, EIA, OFR | UST par curve, Brent, OFR Financial Stress Index (dashboard only, not served by the API)                                       | daily                                                                         |
| Fund documents                    | B3 FNET            | document register (metadata only), including FIDC restatements                                                                 | daily                                                                         |
| Class benchmarks and ETF snapshot | ANBIMA, Apify      | monthly class figures; scraped ETF NAV and price (gated on `APIFY_TOKEN`)                                                      | monthly / daily                                                               |

Where each dataset lands, at what grain and what is ingested but not yet served: [api-docs/data-inventory.mdx](api-docs/data-inventory.mdx) and [docs/reference/DATA_INVENTORY.md](docs/reference/DATA_INVENTORY.md). The schema is `src/store/schema.sql` plus the append-only `src/store/migrations/`.

## How it works

Fetch (`src/fetchers/`, HTTP only), parse (`src/parsers/`, validated rows), store (`src/store/pg_client.py`, upsert on the natural key), orchestrated by `src/pipeline/`. Everything runs in GitHub Actions against Supabase; there is no server to keep up. Times are UTC-3, with UTC in parentheses.

- **03:00 UTC-3 (06:00 UTC), `daily_ingest.yml`:** schema and migrations, `run_daily`, `ANALYZE`, analytical rebuild, dashboard deploy hook. If a source fails the run goes red, but the last three steps still run; only a failed probe, schema apply or analytical apply holds them back.
- **04:30 UTC-3 (07:30 UTC), `health.yml`:** reads the audit log and the tables, fails loudly when they disagree.
- **05:00 UTC-3 (08:00 UTC), `watchdog.yml` and `publish_check.yml`:** re-run stale slices; confirm the public URL serves the new build.
- **On demand, `backfill.yml`:** one entity and year range at a time.

The system in four short pages, in `docs/architecture/`:

| Page                                          | Answers                                                        |
| --------------------------------------------- | -------------------------------------------------------------- |
| [SYSTEM](docs/architecture/SYSTEM.md)         | What the parts are, who reads what, which boundaries matter    |
| [DATA_FLOW](docs/architecture/DATA_FLOW.md)   | How a source file becomes a row, a matview and an `api` answer |
| [OPERATIONS](docs/architecture/OPERATIONS.md) | The daily timeline, and what a failed run leaves behind        |
| [DECISIONS](docs/architecture/DECISIONS.md)   | The rules already decided, each with its source                |

Where every doc lives: [docs/README.md](docs/README.md).

## How it is read

| Surface    | What it is                                                                                                                                                                                          | Link                                                                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Read API   | Schema `api` over PostgREST: `rpc/catalog` and `rpc/coverage` first, then typed functions and the `api.panel` primitive. A request over one 1,000-row page is refused with `22023`, never truncated | [`scalar/`](scalar/), [`api-docs/`](api-docs/quickstart.mdx)                                                                          |
| `serve/`   | Local read-only Flask adapter over schema `api`; not the public API                                                                                                                                 | [docs/reference/API.md](docs/reference/API.md)                                                                                        |
| MCP server | Read-only remote MCP, one tool per `api` endpoint, live since 2026-09-25 at `https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp`                                                        | [`api-docs/mcp.mdx`](api-docs/mcp.mdx), [`supabase/functions/silo-mcp/`](supabase/functions/silo-mcp/)                                |
| Dashboard  | `dashboard/`, Evidence.dev static snapshot (19 pages, including `/dormant`), rebuilt once a day by the deploy hook                                                                                  | [live site](https://silo-bz-deloslabs.vercel.app/), [page list](dashboard/pages/index.md), [dashboard/README.md](dashboard/README.md) |
| Webapp     | `webapp/`, Evidence.dev site over the CIA Aberta tables (financials, Fato Relevante feed)                                                                                                           | [webapp/README.md](webapp/README.md)                                                                                                  |
| Notebooks  | Runnable end-to-end examples                                                                                                                                                                        | [`notebooks/`](notebooks/)                                                                                                            |

Sign-in (GitHub OAuth, [`/signin.html`](https://silo-bz-deloslabs.vercel.app/signin.html)) raises the caps and the query budget for a token holder. A merge does not rebuild the dashboard: only the deploy hook does, so to publish sooner dispatch `daily_ingest` with `rebuild_dashboard=true`.

## Operating it

| Workflow           | When                                     | What                                                                                                                                                                                                                                                                                                                                             |
| ------------------ | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `test.yml`         | every PR and push                        | the offline pytest suite; on dispatch, a read-only `api.*` smoke against production                                                                                                                                                                                                                                                              |
| `daily_ingest.yml` | 03:00 UTC-3 (06:00 UTC), and on dispatch | `daily` is the scheduled run, ANALYZE and analytical refresh included; `analytics-only` is just those two; `b3-backfill` loads yearly COTAHIST zips; `b3-cash-dividends` loads B3's cash-distribution history; `b3-trade-consolidated` loads the fixed income ETF prints. `rebuild_dashboard=true` also fires the deploy hook after a manual run |
| `watchdog.yml`     | 05:00 UTC-3 (08:00 UTC)                  | self-healing re-run of stale slices                                                                                                                                                                                                                                                                                                              |
| `health.yml`       | scheduled                                | the health gates; files an issue on failure                                                                                                                                                                                                                                                                                                      |
| `backfill.yml`     | on dispatch                              | historical fills, one entity at a time; `fi_doc_type` repairs one FI source; `fnet_start` / `fnet_end` / `fnet_sweep` make an FNET-only dispatch                                                                                                                                                                                                 |

Secrets: `POSTGRES_URL` (Supabase, `sslmode=require`); `VERCEL_DEPLOY_HOOK_URL` (deploy hook of the Vercel project `silo-bz` on `main`, team `deloslabs`; it is the only thing that publishes the site); `APIFY_TOKEN` (optional). Day-to-day upkeep (checks, audit-log triage, partition rollover, symptom to fix): [docs/reference/DATABASE_MAINTENANCE.md](docs/reference/DATABASE_MAINTENANCE.md). Operator tooling: [scripts/README.md](scripts/README.md).

```bash
python -m src.pipeline.run_daily                       # incremental
python -m src.pipeline.run_backfill --start-year 2019  # historical
python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2024 --end-year 2024  # one entity
python scripts/verify_pipeline.py                      # quality gate against live Supabase
```

Failed fetches raise and write `cvm_ingest_log`; they are not auto-retried. Re-run the same command.

## Working on the code

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/install_hooks.sh      # pre-commit: secrets, syntax
cp .env.example .env               # set POSTGRES_URL
python scripts/apply_schema.py     # schema + migrations
bash scripts/apply_analytical.sh   # analytical layer, after data exists
pytest tests/ -v                   # all offline (DB and HTTP mocked)
```

- **Rules and commands:** `AGENTS.md` is the source of truth; `CLAUDE.md` only adds Claude Code's hooks.
- **Schema changes:** edit `src/store/schema.sql` and add a new `src/store/migrations/NNN_*.sql`; never edit a historical migration.
- **New dataset or API endpoint:** the steps are in `AGENTS.md` ("Adding a dataset", "Adding an API endpoint").
- **Every branch carries its own docs:** add its row to [docs/planning/CHANGELOG.md](docs/planning/CHANGELOG.md), keep every existing row word for word, and update this README, the planning index and `OPEN_ITEMS.md` where the branch made them stale.

## What is intentionally not here

- **No ingest API.** The pipeline writes via GitHub Actions and the CLI; callers read schema `api`. The old localhost ingest Flask (`app.py`, `src/api/`) is deleted.
- **No fabricated quotes.** The old `b3_calc_api` stays deleted. Quotes come from B3's public COTAHIST zips; an unknown ticker returns an empty result, never a guessed close.
- **No local Postgres, Docker or Alembic.** Supabase Postgres is the single source of truth.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.

## What's next

Open work, known defects and pending operator actions are in [docs/planning/OPEN_ITEMS.md](docs/planning/OPEN_ITEMS.md) (index: [docs/planning/README.md](docs/planning/README.md)).
Build-out history is in [docs/planning/CHANGELOG.md](docs/planning/CHANGELOG.md).
The serving roadmap is [docs/planning/SERVING.md](docs/planning/SERVING.md).
