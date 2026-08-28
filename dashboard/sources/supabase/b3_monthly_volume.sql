-- Monthly B3 traded volume, full 2019-2026 history, standard lot vs odd lot.
--
-- tpmerc '010' is the standard-lot cash market (lote padrão); '020'/'021' are
-- the odd-lot boards (mercado fracionário). Options/forwards/exercises are NOT
-- in these columns — they are on their own chart (b3_options_activity).
--
-- READS THE MATVIEW, NOT THE TAPE. This query used to aggregate all of
-- b3_cotahist on every dashboard build; measured against production on
-- 2026-08-28 it ran for 26 minutes and took the production build past Vercel's
-- 45-minute ceiling, so the site did not rebuild at all. mv_b3_monthly_activity
-- (migration 30) does that pass once a day instead. Same numbers, ~100 rows.
--
-- grain='tpmerc' is the per-board-code row. Filter on grain explicitly: a NULL
-- in instrument_subtype means "rolled up" on one row and "this instrument has
-- no subtype" on another, and only the label tells them apart.
--
-- n_sessions comes from the '010' row alone rather than summing boards: every
-- trading session prints on the standard lot, so that row's session count IS
-- the month's, while adding the odd-lot row would count the same days twice.
--
-- No latest_complete_period() clamp: COTAHIST is session prints, complete by
-- construction, so the series is bounded by the tape itself.
--
-- ZERO-ROW SAFETY: the generate_series month spine drives the row count and the
-- aggregate is LEFT JOINed on. On an empty matview the coalesce'd upper bound
-- collapses the spine to one month of NULLs — never zero rows, never a 0-byte
-- parquet (see delinquency_trend.sql for why that matters).
with bounds as (
  select coalesce(
           (select max(period) from mv_b3_monthly_activity),
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
    period,
    sum(volume) filter (where tpmerc = '010')           / 1e9 as std_lot_volume_bn,
    sum(volume) filter (where tpmerc in ('020', '021')) / 1e9 as odd_lot_volume_bn,
    max(n_sessions) filter (where tpmerc = '010')            as n_sessions,
    max(n_tickers)  filter (where tpmerc = '010')            as n_cash_tickers
  from mv_b3_monthly_activity
  where grain = 'tpmerc'
    and tpmerc in ('010', '020', '021')
  group by period
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
