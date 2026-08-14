-- Latest available snapshot per conformed asset class.
--
-- The literal class list (the CASE arms of dim_fund_category,
-- src/store/analytical/13_dim_classification.sql) is the row driver and
-- asset_class_performance() is LEFT JOINed onto it, so this is a fixed 9 rows
-- even when fact_fund_monthly is empty. A 0-row source writes a zero-byte
-- parquet and takes the build down, so structural non-emptiness is the point.
--
-- Each class is shown at ITS OWN latest period (DISTINCT ON over a trailing
-- 13-month window), not at one shared industry period, and that period is a
-- visible column. The alternative — pinning every class to max(period) — is
-- wrong here: FIP reports yearly and is stored at 31-DEC of its reporting year,
-- a date in the future for most of the year, so a shared max(period) would be a
-- FIP-only period and would blank every other class.
--
-- Classes are therefore NOT necessarily as-of the same date. Read the period
-- column before comparing two rows.
with classes (asset_class) as (
  values
    ('Fixed Income'), ('Equity'), ('Multimarket'), ('Other FI'),
    ('Structured Credit'), ('Real Estate'), ('Agribusiness'),
    ('Private Equity'), ('Other')
),
latest_per_class as (
  select distinct on (asset_class) *
  from asset_class_performance(
    (date_trunc('month', current_date) - interval '12 months')::date,
    (current_date + interval '1 year')::date,
    null
  )
  order by asset_class, period desc
)
select
  c.asset_class,
  -- Evidence renders a NULL date from Parquet as Unix epoch (1970-01-01).
  -- This is a table label, not a chart axis; text preserves an honest blank.
  to_char(t.period, 'YYYY-MM-DD') as period,
  t.n_funds,
  t.total_aum      / 1e9 as aum_bn,
  t.net_flow       / 1e9 as net_flow_bn,
  t.total_cotistas / 1e6 as cotistas_mm,
  round(t.median_yield, 2) as median_yield_num2
from classes c
left join latest_per_class t on t.asset_class = c.asset_class
order by aum_bn desc nulls last
