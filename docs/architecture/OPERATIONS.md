# Operations

Times in UTC-3, with UTC in parentheses.

```
03:00 (06:00)  daily_ingest ─┬─ probe CVM ─────────── unreachable → the whole ingest is skipped
                             ├─ apply schema + migrations
                             ├─ run_daily: CVM → BACEN → IBGE → B3 → BDI → ANBIMA → ETF
                             │       any source failed → exit 1, the run stays red, the next three still run
                             ├─ ANALYZE               skipped only if the probe or schema apply failed
                             ├─ apply_analytical.sh   rebuilds or refreshes every matview, and api; smoke guards
                             ├─ Vercel deploy hook    dashboard build, 17 to 45 min; needs the apply green
                             └─ B3 events · rates/market · FNET register · fnet-diff   (run even after a failure)
04:30 (07:30)  health         read-only gate: errors, stuck slices, fact_fund_monthly lag, disk, anon exposure
05:00 (08:00)  watchdog       stale or unhealed? → re-run run_daily, B3 events and market (data only)
05:00 (08:00)  publish_check  is the new build on the public URL? if not, promote it
after a run    publish_check  also runs when a Daily CVM Ingest run ends green, or red with the
                              hook step done; waits up to 45 min for the build, then promotes
                              it (interim, OPEN_ITEMS item 8)
```

## A red day

- Rows that landed stay landed.
- One red source does not hold back the matviews, `api.panel` or the dashboard:
  ANALYZE, the apply and the hook run after a failed `run_daily`, and the run
  stays red. Accepted risk: they then reflect partly fresh data, the red source
  possibly a day old. `landed_at` and `api.coverage()` say which source.
- A probe or schema failure, or a failed apply, still holds back the apply and
  the hook: they stay at the last good run until the next one, or
  `mode=analytics-only` with `rebuild_dashboard=true`.
- Plain-view endpoints (quotes, short interest) show new data at once. Their
  matview-fed columns do not: `days_to_cover` joins `mv_b3_adtv_21`, and
  `fund_type` in `api.fund_quotas` falls back to `mv_b3_isin_subtype`.
- A GitHub issue titled "Daily ingest is failing" is opened, or commented on.
- The watchdog heals data only. It runs neither the analytical apply nor the
  deploy hook.
- Health and the watchdog count errors only for slices the daily run re-reads
  (`src/pipeline/daily_window.py`). Older ones are backfill work.

## Changes

- PR → `test.yml` (pytest, SQL compile on an ephemeral Postgres) → auto-merge.
- A merge deploys nothing to the database. Migrations apply on the next
  workflow run; analytical SQL applies on the next scheduled run or
  `analytics-only`. `silo-mcp` needs `deploy_mcp.yml`; the Cloudflare demo
  Worker (`deploy/cloudflare/`) needs `deploy_cloudflare.yml`.
- A merge does not publish the dashboard either: `vercel.json` disables
  git-triggered production deployments on `main`. Only the deploy hook
  publishes, from a scheduled run whose apply succeeded or a dispatch with
  `rebuild_dashboard=true`.
- Writers share the `supabase-ingest` concurrency group. Health and
  publish_check are read-only and may overlap.

## Not automated

- `scripts/verify_pipeline.py` is run by hand.
- DB Health checks matview lag on `fact_fund_monthly` only. The other matviews
  are refreshed by the same apply, so they go stale together with it.
- The Scout, Builder and Sentinel agents are defined in `.claude/agents/`, but
  no workflow or routine schedules them (checked 2026-09-29).

Deeper: [database maintenance](../reference/DATABASE_MAINTENANCE.md),
[Supabase operations](../reference/supabase_operations.md).
