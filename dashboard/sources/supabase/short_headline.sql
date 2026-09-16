-- Headline strip for /short: the latest lending session in one row.
--
-- The lending tables are bounded by B3's ~21-business-day retention, so there
-- is no partition-pruning problem here — the whole table is at most ~60k rows.
-- What the strip must be honest about is DEPTH: `sessions_held` says how much
-- history SILO has actually captured, because B3 keeps none of it and the
-- series can only be as long as the daily job has been running.
--
-- Zero-row safe: every aggregate is over a single row, and coalesce keeps the
-- strip rendering (as zeros / nulls) on a database that has not ingested yet.
with latest as (
  select max(trade_date) as trade_date from fact_short_interest_daily
)
select
  l.trade_date,
  coalesce(count(*) filter (where s.categoria in ('SHARES','UNIT')), 0)  as tickers_short,
  coalesce(sum(s.short_brl), 0)                                          as short_brl,
  coalesce(sum(s.short_brl) filter (where s.categoria in ('SHARES','UNIT')), 0)
                                                                         as short_brl_equities,
  max(s.pct_float) filter (where s.float_basis = 'index_free_float')      as max_pct_float,
  (select count(distinct trade_date) from fact_short_interest_daily)      as sessions_held,
  (select min(trade_date)            from fact_short_interest_daily)      as first_session
from latest l
left join fact_short_interest_daily s on s.trade_date = l.trade_date
group by l.trade_date
