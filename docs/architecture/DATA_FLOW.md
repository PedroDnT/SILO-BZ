# Data flow

```
source file or API
   │  fetcher            HTTP only, retries; 404 → "not published"
   ▼
parser / field map       typed rows; a bad row is dropped, never guessed
   ▼
pipeline slice           audit start → upsert ON CONFLICT (natural key) → audit finish
   ▼
landing table            public: cvm_* · b3_* · bacen_* · cia_* · fnet_* · mkt_*
   ▼
normalizing views        pick the filing version, the market, the instrument type, the identity
   ▼
dim_ / fact_ matviews    star schema at (entity, period), rebuilt by the analytical apply
   ▼
schema api               1,000-row cap that refuses (22023), NULL never 0, labels, catalog() / coverage()
```

## Ingest

- A **slice** is one (source, doc_type, period). It ends `ok`, `skipped` (the
  source has not published yet) or `error` (ours to fix).
- Daily windows heal late publication: CVM 4 months (gap-aware), COTAHIST 7
  days, BACEN 30 days. Deep history is manual: `backfill.yml`,
  `market_backfill.yml`, `daily_ingest` `mode=b3-backfill`.
- The B3 BDI group (lending, investor flow) has no backfill. See the ratchet in
  [SYSTEM](SYSTEM.md).

## Analytical

- Plain views change the moment rows land.
- Matviews (`dim_fund`, `fact_fund_monthly`, `mv_period_completeness`, …) change
  only when `scripts/apply_analytical.sh` drops and recreates them.
- `mv_b3_isin_subtype` and `mv_b3_monthly_activity` are created in `schema.sql`,
  because a view depends on the first. The same apply refreshes them
  (`22_b3_tape_matviews.sql`), and also `mv_b3_cash_event`, created by migration
  56 (it reads `cia_ticker`): the cash events behind `close_total_return`,
  resolved once there because the ISIN join costs seconds per call.
- Nothing depends on pg_cron. The live database has none (checked 2026-09-29),
  so the jobs in `08_cron_schedules.sql` do not run.

## Serving

| Path                          | Reads                  | Fresh as of           |
| ----------------------------- | ---------------------- | --------------------- |
| PostgREST, SDK, `silo-mcp`    | `api.*`                | live database         |
| `serve/` (local only)         | `api.*`                | live database         |
| dashboard                     | `public`, at build     | last successful build |
| research job                  | landing tables         | when dispatched       |

Deeper: [API](../reference/API.md), [data inventory](../reference/DATA_INVENTORY.md).
