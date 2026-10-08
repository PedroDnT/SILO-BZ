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
- Daily windows heal late publication: CVM 4 months (gap-aware), the four CDA
  blocks every month through M+5 (CVM completes them about 90 days late), last
  year's FII files from January to March, COTAHIST and
  B3's consolidated trade file (in `run_b3_events`) 7 days, BACEN 30 days. Deep history is manual:
  `backfill.yml`, `market_backfill.yml`, `daily_ingest` `mode=b3-backfill` and
  `mode=b3-trade-consolidated` (B3 kept that file from 2025-06-10 only).
- A re-read CDA month replaces the rows of each fund in the file, so a
  dropped or re-filed position goes (`cvm_ingest_log.rows_deleted`). Funds
  missing from the file keep theirs.
- The B3 BDI group (lending, investor flow) has no backfill. See the ratchet in
  [SYSTEM](SYSTEM.md).
- OTC DEB (migration 74): `b3_credit_capture` saves raw CSV and knowledge time;
  `fact_credit_market` stores long metrics. Missing sessions/drops fail the slice.
  Daily capture is opt-in pending rollout; history uses weekly slices.

## Analytical

- Plain views change the moment rows land.
- Matviews (`dim_fund`, `fact_fund_monthly`, `mv_period_completeness`, …) change
  only when `scripts/apply_analytical.sh` drops and recreates them.
- `mv_b3_isin_subtype` and `mv_b3_monthly_activity` are created in `schema.sql`,
  because a view depends on the first. The same apply refreshes them
  (`22_b3_tape_matviews.sql`), and also `mv_b3_cash_event`, created by migration
  56 (it reads `cia_ticker`): the cash events behind `close_total_return`,
  resolved once there because the ISIN join costs seconds per call.
- `mv_fund_holdings_monthly` (`30_fund_holdings.sql`) is the one daily pass over
  the CDA holdings tables, which have no index on period; `/holdings` reads it.
- `mv_fund_name_history` (`31_api_portfolio.sql`) holds every name a fund ever
  filed (CDA and registry) behind a trigram index; `api.portfolio_resolve` reads
  it, rebuilt by the same apply. `portfolio_lookthrough` reads the CDA tables
  only by CNPJ and one month; `portfolio_instruments` reads them only by
  `cd_ativo` and one month, and `cvm_securit_serie` by CETIP code (migration 73).
- `api.portfolio_fee_peers` (`31_api_portfolio.sql`) groups the latest FI Extrato
  fees of active funds by class, FUNDO_COTAS and scope (30-peer minimum), plus ETFs
  via `portfolio_class_index` (generated from a reviewed YAML) and
  `etf_market_snapshot`. `class_return_distribution` reads `fact_fund_monthly`;
  `portfolio_equivalents` reads the same view (approved pairs), `cvm_etf_registry`
  and `etf_market_snapshot`.
- Nothing depends on pg_cron. The live database has none (checked 2026-09-29),
  so the jobs in `08_cron_schedules.sql` do not run.

## Serving

| Path                       | Reads              | Fresh as of           |
| -------------------------- | ------------------ | --------------------- |
| PostgREST, SDK, `silo-mcp` | `api.*`            | live database         |
| `serve/` (local only)      | `api.*`            | live database         |
| dashboard                  | `public`, at build | last successful build |
| research job               | landing tables     | when dispatched       |

COTAHIST 021=block, 020=odd; [API](../reference/API.md); [inventory](../reference/DATA_INVENTORY.md).
