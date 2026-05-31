# Supabase database operations

The pipeline stores all data in **Supabase Postgres** (project
`zcjbtpxuhdekpwcxmepn`). The code is **DB-agnostic** — everything reads
`POSTGRES_URL` via `src/store/pg_client.py` (`get_pg_client`, psycopg2). Pointing
that one variable at Supabase is the entire wiring; there are no code changes.

This runbook covers applying the schema, ingesting data, and validating a
Supabase project from scratch (e.g. a fresh project, a reset, or a parity check).

## Prerequisites

1. The Supabase project: `zcjbtpxuhdekpwcxmepn`.
2. The **Session pooler** connection string (Supabase dashboard → Connect):
   `postgresql://postgres.zcjbtpxuhdekpwcxmepn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
   - Use the **session pooler (port 5432)**, not the transaction pooler (6543):
     DDL/migrations and `execute_values` bulk upserts are happiest on a session
     connection, and it's IPv4 (works from CI/GitHub Actions). `scripts/db_parity.py`
     and `scripts/_check_conn.py` rewrite `:6543`→`:5432` defensively, so a
     transaction-pooler string still works for those checks.
3. **Check storage/plan**: the FI daily table alone is millions of rows (several
   GB). Confirm the Supabase plan has enough disk before re-ingesting the full
   backfill (Free tier is 500 MB — not enough for a full history).

## Steps

### 1. Point the env at Supabase
```bash
export POSTGRES_URL="postgresql://postgres.zcjbtpxuhdekpwcxmepn:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```
(Locally: put it in `.env`. For automation: set the **GitHub secret**
`POSTGRES_URL` — see step 7.)

### 2. Preflight the target
```bash
python scripts/db_parity.py     # should connect and list 0 user tables on a fresh DB
```

### 3. Apply the schema
```bash
python scripts/apply_schema.py
```
Runs `src/store/schema.sql` then every `src/store/migrations/*.sql` in order, all
idempotent. Expect base tables, the `cvm_fi_diario_YYYY` partitions,
`cvm_etf_registry`, and the `etf_daily` / `etf_latest` / `instrument_activity` views.

### 4. Verify schema parity
```bash
python scripts/db_parity.py     # all expected tables/views present, rows ~0
```

### 5. Ingest the data
Either locally:
```bash
python -m src.pipeline.run_backfill                 # full history, all entities + BACEN
python -m src.pipeline.run_daily                    # current + previous month, ETF/registry seed
```
…or via CI (recommended for the long backfill): set the GitHub secret
`POSTGRES_URL`, then dispatch **CVM Historical Backfill** (`backfill.yml`) and let
the daily cron (`daily_ingest.yml`) take over. The backfill's per-year FI matrix +
`backfill-other` jobs run in parallel; the tuned knobs
(`CVM_UPSERT_CHUNK_SIZE=5000`, etc.) already apply.

The ETF seed (`src/store/seeds/etf_registry_seed.csv`) and the CVM-175 registry
load automatically as part of `ingest_etf_registry` / `ingest_fund_registry_cvm175`
in both backfill and daily — no separate data copy.

### 6. Validate
```bash
python scripts/db_parity.py --exact          # exact counts
python scripts/verify_pipeline.py            # field-population + business-metric report
psql "$POSTGRES_URL" -f scripts/queries/08_ingest_health.sql
psql "$POSTGRES_URL" -f scripts/queries/12_etf_overview.sql
psql "$POSTGRES_URL" -f scripts/queries/13_instrument_lifecycle.sql
```
Confirm row counts are in the expected ballpark and `cvm_ingest_log` shows
`status='ok'` for the slices.

### 7. Consumers
- **GitHub Actions**: set repo secret `POSTGRES_URL` → Supabase session-pooler URL.
  (Both `daily_ingest.yml` and `backfill.yml` read `secrets.POSTGRES_URL`.)
- **Evidence dashboard** (`dashboard/`): the source dir is `dashboard/sources/supabase/`
  (`name: supabase`, `type: postgres`; the yaml holds no secrets). Credentials load
  from a single env var `EVIDENCE_SOURCE__supabase__connectionString`, read from
  gitignored `dashboard/.env` locally and from project env settings on Evidence
  Cloud. See `dashboard/.env.example`. Point it at the **session pooler** host for
  Evidence Cloud / CI — the direct `db.<ref>.supabase.co:5432` host is IPv6-only
  and fails from IPv4-only build environments. Page queries reference tables bare
  (`from fact_fund_monthly`), so they don't depend on the source name.

## Supabase gotchas to watch

- **Statement timeout**: Supabase sets a default `statement_timeout`. The bulk
  upserts are chunked (5000 rows) so each statement is short, but if a step trips
  the limit, raise it for the ingestion role:
  `ALTER ROLE postgres SET statement_timeout = '0';` (or a high value).
- **Connection limits**: the session pooler caps connections. The pipeline uses a
  single connection per process; the backfill FI matrix runs ≤8 parallel CI jobs —
  well within pooler limits, but don't crank `CVM_*_CONCURRENCY` arbitrarily.
- **RLS / exposure**: tables created via SQL land in `public`, which Supabase's
  auto API (PostgREST) can expose. The pipeline connects directly (not via the
  API), so RLS isn't required to function — but if the project's anon/public API
  is enabled, either enable RLS on these tables or keep the API restricted, so the
  financial data isn't world-readable.
- **`ANALYZE`**: `daily_ingest.yml` runs `ANALYZE` post-ingest; `db_parity.py`
  estimates rely on it. After a manual local backfill, run `ANALYZE;` so the
  estimates (and the planner) are fresh.
