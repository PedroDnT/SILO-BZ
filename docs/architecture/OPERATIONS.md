# Operations

Times in UTC-3, with UTC in parentheses.

```
03:00 (06:00)  daily_ingest ─┬─ probe CVM ─────────── unreachable → the whole ingest is skipped
                             ├─ apply schema + migrations
                             ├─ run_daily: CVM → BACEN → IBGE → B3 → BDI → ANBIMA → ETF
                             │       any source failed → exit 1 → the next three steps are skipped
                             ├─ ANALYZE
                             ├─ apply_analytical.sh   rebuilds the analytical matviews and api; smoke guards
                             ├─ Vercel deploy hook    dashboard build, 17 to 45 min
                             └─ rates/market · FNET register · fnet-diff   (run even after a failure)
04:30 (07:30)  health         read-only gate: errors, stuck slices, fact_fund_monthly lag, disk, anon exposure
05:00 (08:00)  watchdog       stale or unhealed? → re-run run_daily (data only)
05:00 (08:00)  publish_check  is the new build on the public URL? if not, promote it
```

## A red day

- Rows that landed stay landed.
- Matviews, `api.panel` and the dashboard stay at the last green run. They move
  again on the next green run, or on `daily_ingest` `mode=analytics-only` with
  `rebuild_dashboard=true`.
- Plain-view endpoints (quotes, short interest) show new data at once. Their
  matview-fed columns do not: `days_to_cover` joins `mv_b3_adtv_21`, and
  `fund_type` in `api.fund_quotas` falls back to `mv_b3_isin_subtype`.
- A GitHub issue titled "Daily ingest is failing" is opened, or commented on.
- The watchdog heals data only. It runs neither the analytical apply nor the
  deploy hook.

## Changes

- PR → `test.yml` (pytest, SQL compile on an ephemeral Postgres) → auto-merge.
- A merge deploys nothing to the database. Migrations apply on the next
  workflow run; analytical SQL applies on the next green run or
  `analytics-only`. `silo-mcp` needs `deploy_mcp.yml`.
- A merge does not publish the dashboard either: `vercel.json` disables
  git-triggered production deployments on `main`. Only the deploy hook
  publishes, from a green scheduled run or a dispatch with
  `rebuild_dashboard=true`.
- Writers share the `supabase-ingest` concurrency group. Health and
  publish_check are read-only and may overlap.

## Not automated

- `scripts/verify_pipeline.py` is run by hand.
- No check watches the freshness of `mv_b3_isin_subtype` or
  `mv_b3_monthly_activity`.
- The Scout, Builder and Sentinel agents are defined in `.claude/agents/`, but
  no workflow or routine schedules them (checked 2026-09-29).

Deeper: [database maintenance](../DATABASE_MAINTENANCE.md),
[Supabase operations](../supabase_operations.md).
