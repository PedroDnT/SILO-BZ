# Operations

Times UTC-3; UTC in ( ).

```
03:00 (06:00)  daily_ingest ─┬─ probe CVM             unreachable → skip CVM, run red
                             ├─ apply schema + migrations
                             ├─ run_daily: CVM → BACEN → IBGE → ANBIMA → B3 → BDI
                             │       source failed → exit 1/red; next three still run
                             ├─ ANALYZE               skipped only if the schema apply failed
                             ├─ apply_analytical.sh   refresh matviews/api; smoke guards
                             └─ Vercel deploy hook    dashboard build, 17-45 min; needs the apply green
               parallel jobs after ingest, even if red (≤75 min): B3 events · rates (B3 ≤15m) · ETF · FNET → fnet-diff
after daily    health         read-only: errors, stuck, freshness, B3 sessions, disk, anon
after daily    watchdog       stale/unhealed? re-run run_daily, B3 events, market, ETF;
                              FNET, fnet-diff on own flags; fallback crons 07:30/07:40 (10:30/10:40)
05:00 (08:00)  publish_check  public URL stale? promote; ERRORed → red
after a run    publish_check  green daily run, or red with hook done: wait ≤45 min, promote (no-op, item 8)
Sat 09:00 (12:00) anbima_capture priced codes; private
Sun 12:17      snapshot       research Parquet + manifest, read-only; opt-in
```

`rj_collect` (RJ, #877) is dispatch-only.

## A red day

- Landed rows stay. After a failed `run_daily`, ANALYZE, the apply and deploy
  hook still run. Matviews, `api.panel`, the dashboard may be partly stale; run is red.
  `landed_at` and `api.coverage()` show freshness by source.
- Schema/apply failures hold back publication until a successful run or
  `mode=analytics-only` with `rebuild_dashboard=true`.
- Plain views (quotes, short interest) show new data at once, not their
  matview-fed columns: `days_to_cover` joins `mv_b3_adtv_21`;
  `fund_type` in `api.fund_quotas` falls back to `mv_b3_isin_subtype`.
- Issue "Daily ingest is failing" or "DB Health is failing" opens or updates.
- Watchdog heals data only: no analytical apply, no deploy hook. It and health
  count errors only in slices the daily run re-reads (`src/pipeline/daily_window.py`).

## Changes

- PR → `test.yml` (pytest, SQL compile) → auto-merge.
  Hook and PR CI share a DB-password guard.
  A PR touching `src/portfolio/` or `deploy/cloudflare/engine/` also runs
  `engine_image.yml` (build and smoke, no publish).
- A merge deploys nothing to the database. Migrations apply on the next
  workflow run, analytical SQL on the next scheduled run or `analytics-only`.
  `silo-mcp` needs `deploy_mcp.yml`; the Cloudflare demo
  needs `deploy_cloudflare.yml`, which ends with a
  paid end-to-end report.
- Dashboard merges do not publish (`vercel.json` disables production Git
  deploys); the deploy hook does, after a weekday scheduled apply or
  `rebuild_dashboard=true`.
- Writers share the `supabase-ingest` group, one pending run: dispatch one at
  a time, a waiting one is replaced. Watchdog skips a cancelled daily.
- Trace keys are pending. Background storage validates artifacts, writes the
  trace last, logs fixed codes, keeps reports on failure.
- Schema replay skips matching indexes, absent constraints.
- DEB: daily/watchdog pass `vars.B3_CREDIT_ENABLED`; only `1` enables
  7-day refresh with smaller-slice recovery. `mode=b3-credit` loads
  one owner-approved slice, 7 days at most (item 18). `credit_implied`
  follows at 06:00 (09:00).
  [Contract](../reference/research/debenture-secondary-market-capture.md).

## Not automated

- `scripts/verify_pipeline.py` runs by hand. All issuers' B3 events once:
  `mode=b3-corporate-events-full`.
- DB Health checks matview lag on `fact_fund_monthly` only; the others share
  its apply and go stale with it.
- Sentinel runs daily since 2026-10-06; Scout and Builder are paused
  (`.claude/agents/`, item 13).

See [database maintenance](../reference/DATABASE_MAINTENANCE.md),
[Supabase operations](../reference/supabase_operations.md).
