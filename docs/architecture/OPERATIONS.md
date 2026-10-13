# Operations

Times in UTC-3, with UTC in parentheses.

```
03:00 (06:00)  daily_ingest ─┬─ probe CVM ─────────── unreachable → skip ingest
                             ├─ apply schema + migrations
                             ├─ run_daily: CVM → BACEN → IBGE → B3 → BDI → ANBIMA → ETF
                             │       source failed → exit 1/red; next three still run
                             ├─ ANALYZE               skipped only if the probe or schema apply failed
                             ├─ apply_analytical.sh   refresh matviews/api; smoke guards
                             ├─ Vercel deploy hook    dashboard build, 17 to 45 min; needs the apply green
                             └─ B3 events · rates/market · FNET register · fnet-diff   (run even after a failure)
04:30 (07:30)  health         read-only gate: errors, stuck slices, fact_fund_monthly lag, disk, anon exposure
05:00 (08:00)  watchdog       stale or unhealed? → re-run run_daily, B3 events and market (data only)
05:00 (08:00)  publish_check  public URL stale? promote; ERRORed → red
after a run    publish_check  green daily run, or red with hook done: wait ≤45 min, promote
                              (no-op while Vercel auto-assigns; item 8)
08:07 (11:07)  rj_collect     RJ: AJ sites + DJEN (BR relay); red on failure
```

## A red day

- Rows that landed stay landed.
- After a failed `run_daily`, ANALYZE, the apply and deploy hook still run.
  Matviews, `api.panel` and the dashboard may be partly stale; the run stays red.
  `landed_at` and `api.coverage()` show freshness by source.
- Probe/schema/apply failures hold back publication until a successful run or
  `mode=analytics-only` with `rebuild_dashboard=true`.
- Plain views (quotes, short interest) show new data at once. Their
  matview-fed columns do not: `days_to_cover` joins `mv_b3_adtv_21`, and
  `fund_type` in `api.fund_quotas` falls back to `mv_b3_isin_subtype`.
- An issue "Daily ingest is failing" is opened or commented on.
- Watchdog heals data only; no analytical apply or deploy hook.
- Health and the watchdog count errors only for slices the daily run re-reads
  (`src/pipeline/daily_window.py`). Older ones are backfill work.

## Changes

- PR → `test.yml` (pytest, SQL compile on an ephemeral Postgres) → auto-merge.
  Hook/PR CI share a sanitized dotenv/DB-password guard; CI checks PR additions.
  A PR touching `src/portfolio/` or `deploy/cloudflare/engine/` also runs
  `engine_image.yml`: it builds and smokes the engine image, publishes nothing.
- A merge deploys nothing to the database. Migrations apply on the next
  workflow run; analytical SQL applies on the next scheduled run or
  `analytics-only`. `silo-mcp` needs `deploy_mcp.yml`; the Cloudflare demo
  (`deploy/cloudflare/`, Worker plus engine Container) needs
  `deploy_cloudflare.yml`, which ends with a paid end-to-end report.
- Dashboard merges do not publish: `vercel.json` disables production Git deploys.
  The deploy hook publishes after a weekday scheduled apply or a dispatch
  with `rebuild_dashboard=true`.
- Writers share the `supabase-ingest` concurrency group. Health and
  publish_check are read-only and may overlap.
- Trace keys are pending. Background storage validates artifacts, writes the
  trace last and logs fixed codes; failures preserve reports.
- Schema replay skips matching indexes and absent constraints.
- DEB: daily/watchdog pass `vars.B3_CREDIT_ENABLED`; only `1` enables
  seven-day refresh with smaller-slice recovery.
  [Contract](../reference/research/debenture-secondary-market-capture.md).

## Not automated

- `scripts/verify_pipeline.py` is run by hand.
- DB Health checks matview lag on `fact_fund_monthly` only; the other matviews
  refresh in the same apply and go stale with it.
- No workflow or routine schedules the Scout, Builder and Sentinel agents
  (`.claude/agents/`; checked 2026-09-29).

Deeper: [database maintenance](../reference/DATABASE_MAINTENANCE.md),
[Supabase operations](../reference/supabase_operations.md).
