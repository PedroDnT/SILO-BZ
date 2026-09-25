# Research reliability assessment

This assessment tracks the implementation work on `codex/research-quality`. It
describes the current code as inspected on 2026-09-23; live data findings and
the ranked opportunity list belong in the research results produced by this
workstream.

## Current path from source to researcher

| Stage | Current implementation | Verification surface |
| --- | --- | --- |
| Fetch and parse | `src/fetchers/` and `src/parsers/` read CVM, B3, BACEN, IBGE, and other sources | Offline source fixtures and fetch/parse tests |
| Store | `src/pipeline/` validates and upserts natural keys into `src/store/schema.sql`; each slice writes `cvm_ingest_log` | Pipeline tests, ingest log, `scripts/verify_pipeline.py` |
| Model | `src/store/analytical/` builds views, materialized views, and schema `api` | `.github/workflows/test.yml` applies schema, migrations, and analytical SQL to ephemeral Postgres |
| Serve | PostgREST reads schema `api`; `serve/` adapts selected reads to HTTP | SQL contract tests, SDK tests, Flask tests, CI SQL execution, local smoke |
| Research | `sdk/silo_client/` and `notebooks/` consume the public read contract | Nine existing notebooks, coverage and pagination checks |
| Presentation | `dashboard/` and `webapp/` build Evidence pages from SQL snapshots | Page/source assertions and published-site checks |

## Findings that affect this work

1. The repo already executes schema and analytical SQL in CI, including value
   checks for FI/FIP aggregation and caller tiers. Additional SQL test machinery
   should target uncovered behavior rather than duplicate that gate.
2. `CVMIngestor` combines run policy, audit state, and dataset methods in one
   large class. Tests frequently bypass its constructor to avoid a database
   connection. Injecting its dependencies and isolating slice planning makes
   the run path easier to exercise while retaining the existing audit contract.
3. The local API smoke script assumes Linux Postgres paths and a `postgres`
   OS user. This macOS checkout needs a portable local driver before that smoke
   can run here. GitHub CI remains the cross-platform SQL execution gate.
4. `docs/DATA_INVENTORY.md` already records held-but-unserved candidates and
   some integrity concerns. Those entries are leads, not proof of current live
   coverage; the opportunity study must compare each with schema `api`, catalog,
   SDK, and source records.
5. The existing notebooks answer single-domain questions. The new evaluation
   must test cross-dataset joins, incompatible periods, missing observations,
   and whether an agent can produce a reproducible conclusion without guessing.
6. The original `cia_account` constraint in migration 04 omits
   `dt_ini_exerc`, but migration 29 widens the final natural key to include it.
   The migration and field-map regression test are the relevant current
   evidence when assessing cumulative versus discrete ITR periods.
7. B3 index portfolios are already fetched and landed by `b3_pipeline.py`;
   the short-interest analytical layer uses them. Any proposed index-portfolio
   addition must identify a distinct missing vintage or public serving path
   rather than claim that the whole source is absent.

## Implemented changes and final local evidence

| Area | Before | After | Evidence |
| --- | --- | --- | --- |
| Company filings | `financials` exposed the latest stored version only | `financial_statement_history` serves bounded raw statement lines across stored versions, preserving filed scale/currency and exact-key header provenance | SQL contract, SDK/OpenAPI tests, local Postgres smoke |
| FII property reports | Property rows were not available through the public API/SDK | `fii_property_history` exposes source rows for an exact fund and date window, keeping nulls and row identity honest | SQL contract, SDK/OpenAPI tests; Evidence page no longer treats an undocumented value as a concentration threshold |
| BCB Focus | Weekly expectations existed in storage but were not available through the public API/SDK | `focus_expectations` serves bounded observations by survey date and forecast horizon | SQL contract, SDK/OpenAPI tests, local Postgres smoke |
| CVM orchestration | Planning and execution were coupled to concrete fetchers/database setup | Fetcher/database dependencies are injectable and monthly/annual work planning is isolated | `tests/test_ingestor.py` |
| Agent discovery | Docs could lead an agent directly to example datasets | Agent docs now require catalog → dataset docs/metadata → coverage → defensible join discovery before selecting data | Agent API docs updated; benchmark prompts contain only research questions |
| Local API proof | macOS smoke runner assumed Linux Postgres paths/account | macOS local Postgres flow runs and returns catalog/tools/coverage 200, unknown ticker 404 | `SMOKE PASS` |

Final local verification on 2026-09-23: **1,554 tests passed** (`pytest tests/`),
including deterministic SQL/API/SDK contracts; isolated local Postgres smoke
passed; Evidence `npm run sources` completed against the empty local database;
`git diff --check` passed. The smoke verifies the applied SQL and HTTP contract,
not production data freshness or row-level correctness against a populated
warehouse. The full Evidence build cannot be verified from the empty database:
Evidence emits invalid parquet for a genuinely empty source (`aum_by_entity`),
then the build fails while loading that parquet. A populated, non-production
snapshot is needed to validate rendered charts and build output.

The three research examples are runnable calculations with explicit source,
join, and limitation notes; they are reference demonstrations rather than live
agent tool-call recordings. The 12-case benchmark remains **unverified** because
the OpenAI Platform rejected key creation and no existing key was available.
No OpenAI API calls, paid evaluations, production database writes, migrations,
deployments, historical backfills, or data publication were performed. Thus no
agent accuracy, latency, or spend result is claimed against the US$20 cap.

## Remaining release evidence

- Live public-read freshness and source-reconciliation checks against a
  populated authorized environment.
- The full callable-object matrix is documented in
  `docs/research/api-surface-matrix.md`; refresh its snapshot when SQL grants,
  catalog, SDK, or Flask routes change.
- For each added dataset: published source and natural key, validation losses,
  duplicate rate, observed time range, last source period, last successful
  landing, and one independently calculated research result.
- The 12-case agent evaluation, including rejected or limited answers and
  observed spend against the US$20 cap, after API access is available.

No production database migration or dashboard publication is part of this
assessment. The release package must identify those actions separately.
