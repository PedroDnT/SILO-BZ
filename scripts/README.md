# scripts/

Operator and developer tooling. Nothing here is part of the ingest critical path
except `apply_schema.py` and `apply_analytical.sh`, which CI calls on every run.

Grouped by when you would reach for them.

## Run on every ingest (CI calls these)

| Script                | What it does                                                                                                                                                                                                                                                           |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apply_schema.py`     | Applies `src/store/schema.sql`, then every `src/store/migrations/*.sql` in order. Idempotent. **CI uses `psql` via `.github/actions/apply-schema` instead** — it parses SQL comments correctly and fails on the first real error; this script is the local equivalent. |
| `apply_analytical.sh` | Applies the analytical layer (`src/store/analytical/01…19`) — dims, fact matviews, fraud screens, ranking functions, and schema `api`. Run **after** data exists.                                                                                                      |

## Health and diagnostics (read-only, safe against production)

| Script                        | What it does                                                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `verify_pipeline.py`          | The quality gate. Runs verification queries against live Supabase. **If a change makes this fail, the change is wrong — not the verifier.** |
| `check_staleness.py`          | Ingest-staleness check behind `watchdog.yml`; re-runs ingest when a dataset falls behind.                                                   |
| `audit_coverage.py`           | Reports what data actually exists per table, so a dashboard figure can be judged against its own coverage.                                  |
| `audit_matview_dependents.py` | What a `CASCADE` drop of each matview would destroy. Read before touching `fact_*`.                                                         |
| `db_parity.py`                | Lists user tables/views with row-count estimates — used to compare two databases.                                                           |
| `list_tables.py`              | Every schema / table / row-count / column. Broader than `db_parity.py`, handy for a first look at an unfamiliar database.                   |
| `_check_conn.py`              | Bare connection check. Rewrites `:6543`→`:5432` defensively; see `docs/supabase_operations.md`.                                             |

## Offline development (no Supabase credentials needed)

| Script                  | What it does                                                                                                             |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `seed_local_db.py`      | Seeds a local DuckDB with real CVM data fetched live from dados.cvm.gov.br.                                              |
| `run_analysis_local.py` | Runs the analytical queries against that local DuckDB. Pairs with the seeder for a ~2-minute offline verification.       |
| `explore_cvm_output.py` | Hits real CVM URLs and prints raw field names and sample rows. The first thing to run when a `FIELD_MAP` stops matching. |

## Build and setup

| Script                   | What it does                                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vercel_should_build.sh` | Vercel `ignoreCommand`. Builds only when `dashboard/`, `vercel.json` or itself changed. **Exit codes are inverted per Vercel's contract: 0 SKIPS, 1 BUILDS.** Fails open. |
| `install_hooks.sh`       | Points git at `.githooks/` (pre-commit secret + syntax checks).                                                                                                           |
| `build_etf_seed.py`      | Regenerates the curated B3 ETF seed at `src/store/seeds/etf_registry_seed.csv`.                                                                                           |

## One-off, historical

Kept for provenance. The Supabase cutover is long finished; these are not part of
any current workflow and should not be needed again.

| Script                | What it does                                                             |
| --------------------- | ------------------------------------------------------------------------ |
| `supabase_cutover.py` | Verified the original cutover: connect, confirm the rebuilt schema.      |
| `finish_cutover.sh`   | Driver for that cutover. Referenced only by a comment in `.env.example`. |

## queries/

Thirteen numbered read-only SQL files (`01_market_overview.sql` …
`13_instrument_lifecycle.sql`) used by the verification scripts and for ad-hoc
inspection. They are plain `psql`-runnable SQL, not templates.
