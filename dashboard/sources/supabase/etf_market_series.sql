-- Monthly ETF exchange activity from the B3 COTAHIST tape, for /etf.
--
-- This is the EXCHANGE side of the ETF market — traded price and volume of
-- fund_quota rows classified instrument_subtype = 'etf' (CODBDI 14, via
-- vw_b3_instrument_typed; never guessed from ticker shape) on the standard-lot
-- cash board (tpmerc '010'). It exists because the NAV side is sparse
-- post-CVM-175 (etf_daily's CNPJ join broke); the exchange tape has no such
-- gap. Prices are UNADJUSTED closes straight from COTAHIST.
--
-- median_close is a cross-sectional "typical ETF print" per month — ETFs quote
-- at wildly different price points, so a median, not a mean; it is NOT an
-- index and says nothing about returns. Volume is summed across all ETF rows.
--
-- No latest_complete_period() clamp: session prints are complete by
-- construction; the bound is the tape's own max(trade_date).
--
-- ZERO-ROW SAFETY: generate_series month spine drives the rows, the aggregate
-- is LEFT JOINed — an empty tape yields NULL months, never the 0-row source
-- whose 0-byte parquet kills the Evidence build.
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
    date_trunc('month', trade_date)::date                              as period,
    percentile_cont(0.5) within group (order by preco_fechamento)      as median_close,
    sum(volume) / 1e9                                                  as volume_bn,
    count(distinct codneg)                                             as n_etf_tickers
  from vw_b3_instrument_typed
  where tpmerc = '010'
    and instrument_subtype = 'etf'
  group by date_trunc('month', trade_date)
)
select
  sp.period,
  round(a.median_close::numeric, 2) as median_close,
  a.volume_bn,
  a.n_etf_tickers
from spine sp
left join agg a on a.period = sp.period
order by sp.period
