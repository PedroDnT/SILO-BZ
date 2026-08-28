-- Monthly B3 traded volume, full 2019-2026 history, standard lot vs odd lot.
--
-- tpmerc '010' is the standard-lot cash market (lote padrão); '020'/'021' are
-- the odd-lot boards (mercado fracionário). Options/forwards/exercises are NOT
-- in these columns — they are on their own chart (b3_options_activity).
--
-- No latest_complete_period() clamp: COTAHIST is session prints, complete by
-- construction, so the series is bounded by max(trade_date) of the tape itself.
--
-- ZERO-ROW SAFETY: the generate_series month spine drives the row count and the
-- aggregate is LEFT JOINed on. On an empty table the coalesce'd upper bound
-- collapses the spine to one month of NULLs — never zero rows, never a 0-byte
-- parquet (see delinquency_trend.sql for why that matters).
with bounds as (
  select coalesce(
           (select date_trunc('month', max(trade_date)) from b3_cotahist),
           date '2019-01-01'
         ) as month_end
),
spine as (
  select generate_series(
           date '2019-01-01',
           b.month_end,
           interval '1 month'
         )::date as period
  from bounds b
),
agg as (
  select
    date_trunc('month', trade_date)::date                                as period,
    sum(volume) filter (where tpmerc = '010')            / 1e9           as std_lot_volume_bn,
    sum(volume) filter (where tpmerc in ('020', '021'))  / 1e9           as odd_lot_volume_bn,
    count(distinct trade_date)                                           as n_sessions,
    count(distinct codneg) filter (where tpmerc = '010')                 as n_cash_tickers
  from b3_cotahist
  where tpmerc in ('010', '020', '021')
  group by date_trunc('month', trade_date)
)
select
  sp.period,
  a.std_lot_volume_bn,
  a.odd_lot_volume_bn,
  a.n_sessions,
  a.n_cash_tickers
from spine sp
left join agg a on a.period = sp.period
order by sp.period
