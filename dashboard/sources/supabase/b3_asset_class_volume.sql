-- Monthly standard-lot cash volume by instrument type, long format, plus an
-- ETF-vs-FII split of the fund_quota bucket.
--
-- instrument_type comes from vw_b3_instrument_typed, which classifies from
-- CODBDI/ESPECI/tpmerc — never from ticker shape. Only the cash types are
-- listed here; options and forwards live on their own chart
-- (b3_options_activity). The tpmerc = '010' filter keeps this standard lot so
-- it reconciles with the std-lot column of b3_monthly_volume.
--
-- etf_volume_bn / fii_volume_bn are populated only on the fund_quota rows
-- (instrument_subtype is NULL for every other type by construction); a
-- fund_quota row whose board carries no family signal counts in volume_bn but
-- in neither subtype column — the gap is real, not zero.
--
-- ZERO-ROW SAFETY (copy of the industry_asset_class.sql pattern): the month
-- spine CROSS JOINed to the literal type list drives the row count, aggregates
-- are LEFT JOINed on top — no state of the table can produce the 0-row source
-- that writes a zero-byte parquet and kills the Evidence build. No
-- latest_complete_period() clamp: COTAHIST sessions are complete by
-- construction; the bound is the tape's own max(trade_date).
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
types (instrument_type) as (
  values ('equity'), ('bdr'), ('unit'), ('fund_quota'), ('cash_security')
),
agg as (
  select
    date_trunc('month', trade_date)::date                                 as period,
    instrument_type,
    sum(volume) / 1e9                                                     as volume_bn,
    count(distinct codneg)                                                as n_tickers,
    sum(volume) filter (where instrument_subtype = 'etf') / 1e9           as etf_volume_bn,
    sum(volume) filter (where instrument_subtype = 'fii') / 1e9           as fii_volume_bn
  from vw_b3_instrument_typed
  where tpmerc = '010'
    and instrument_type in ('equity', 'bdr', 'unit', 'fund_quota', 'cash_security')
  group by date_trunc('month', trade_date), instrument_type
)
select
  sp.period,
  t.instrument_type,
  a.volume_bn,
  a.n_tickers,
  a.etf_volume_bn,
  a.fii_volume_bn
from spine sp
cross join types t
left join agg a
  on a.period = sp.period
 and a.instrument_type = t.instrument_type
order by sp.period, t.instrument_type
