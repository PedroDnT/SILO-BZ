# Data flow

```
source file or API
   │  fetcher            HTTP only, retries; 404 → "not published"
   ▼
parser / field map       typed rows; a bad row is dropped, never guessed
   ▼
pipeline slice           audit start → upsert ON CONFLICT (natural key) → audit finish
   ▼
landing table            public: cvm_* · b3_* · bacen_* · cia_* · fnet_* · mkt_* · ibge_* · anbima_* · etf_* · rj_*
   ▼
normalizing views        pick the filing version, the market, the instrument type, the identity
   ▼
dim_ / fact_ matviews    star schema at (entity, period), rebuilt by the analytical apply
   ▼
schema api               1,000-row cap that refuses (22023), NULL never 0, labels, catalog() / coverage()
```

## Ingest

- A **slice** is (source, doc_type, period): `ok`, `skipped` (unpublished, file
  unchanged, CVM probe down: `daily_scope`), or `error`.
- The daily run sends the ETag / Last-Modified an ok slice stored
  (`cvm_source_validator`, 7 days) for CDA, FII, FIP, SECURIT, CIA IPE/FCA; a
  304 is `skipped`, `unchanged:`, fresh to `check_staleness.py`.
- Daily windows heal late publication: CVM 4 months (gap-aware), the four CDA
  blocks every month through M+5 (completed about 90 days late), last
  year's FII files in January-March, COTAHIST and B3's consolidated trade file
  (in `run_b3_events`) 7 days, BACEN 30 days. Current-year ITR/DFP: full on
  Monday (CVM regenerates them Sunday), new documents and lineless headers
  otherwise. Deep history is manual: `backfill.yml`, `market_backfill.yml`,
  `daily_ingest` modes `b3-backfill`, `b3-trade-consolidated` (kept from
  2025-06-10), `b3-credit`, `b3-corporate-events-full`.
- A re-read CDA month replaces each fund's rows in the file, so a dropped
  or re-filed position goes (`cvm_ingest_log.rows_deleted`); absent funds keep theirs.
- B3 BDI (lending, investor flow): a ratchet, no backfill ([SYSTEM](SYSTEM.md)).
- OTC DEB (74): raw CSV + knowledge time; missing sessions fail it.
- ANBIMA debentures, CRI/CRA (80, 82, Playwright): terms, agenda, 5-session
  rates; raw text only on a parse failure. CVM offerings (81): backfill. B3 DEB
  implied rates (83): calculated, private.

## Analytical

- Views change as rows land.
- Matviews (`dim_fund`, `fact_fund_monthly`, `mv_period_completeness`, …) change
  only when `scripts/apply_analytical.sh` recreates them.
- `mv_b3_isin_subtype` and `mv_b3_monthly_activity` are created in `schema.sql`,
  because a view depends on the first. The same apply refreshes them
  (`22_b3_tape_matviews.sql`) and `mv_b3_cash_event` (migration 56; it reads
  `cia_ticker`): the cash events behind `close_total_return`, resolved once
  (the ISIN join is slow).
- `mv_fund_holdings_monthly` (`30_fund_holdings.sql`) is the one daily pass over
  the CDA holdings tables (no period index); `/holdings` reads it.
- `mv_fund_name_history` (`31_api_portfolio.sql`) holds every name a fund ever
  filed (CDA, registry) behind a trigram index for `api.portfolio_resolve`. `portfolio_lookthrough` reads the CDA tables
  only by CNPJ and one month; `portfolio_instruments` filters `cd_ativo` by
  month; debenture returns use exact tickers and median PU from 3+ funds.
- `api.portfolio_fee_peers` (`31_api_portfolio.sql`) groups the latest FI Extrato
  fees of active funds by class, FUNDO_COTAS and scope (30-peer minimum), plus
  ETFs via `portfolio_class_index` (reviewed YAML) and `etf_market_snapshot`. `class_return_distribution` reads `fact_fund_monthly`;
  `portfolio_equivalents` reads the same view (approved pairs), `cvm_etf_registry`
  and `etf_market_snapshot`.
- pg_cron is absent.

## Serving

`credit_market_history`: audited date vintages before code filter; nine metrics
per settlement/classification.

| Path | Reads | Fresh as of |
| --- | --- | --- |
| PostgREST, SDK, `silo-mcp` | `api.*` | live database |
| `serve/` (local only) | `api.*` | live database |
| dashboard | `public`, at build | last successful build |
| research job | landing tables | when dispatched |

[API](../reference/API.md), [inventory](../reference/DATA_INVENTORY.md).
