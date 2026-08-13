-- AUM and flows by conformed asset class, monthly, last 24 months (long format).
--
-- Wraps asset_class_performance() (src/store/analytical/14_ranking_functions.sql)
-- over dim_fund_category. The month spine CROSS JOINed to the literal class list
-- drives the row count (fixed 24 x 9 = 216), with the function LEFT JOINed on
-- top — so no combination of empty tables can produce the 0-row source that
-- writes a zero-byte parquet and kills the Evidence build.
--
-- The class list is exactly the CASE arms of dim_fund_category
-- (src/store/analytical/13_dim_classification.sql). A class with no funds shows
-- as blank, never as zero.
--
-- median_yield_pct: fact_fund_monthly.pct_yield_mes is populated for FII only
-- (monthly dividend yield), so this column is blank for every other class by
-- construction. It is NOT a cross-class return comparison.
with spine as (
  select generate_series(
           date_trunc('month', current_date) - interval '23 months',
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
classes (asset_class) as (
  values
    ('Fixed Income'), ('Equity'), ('Multimarket'), ('Other FI'),
    ('Structured Credit'), ('Real Estate'), ('Agribusiness'),
    ('Private Equity'), ('Other')
),
t as (
  select *
  from asset_class_performance(
    (date_trunc('month', current_date) - interval '23 months')::date,
    current_date,
    null
  )
)
select
  sp.period,
  c.asset_class,
  t.n_funds,
  t.total_aum      / 1e9 as aum_bn,
  t.net_flow       / 1e9 as net_flow_bn,
  t.total_cotistas / 1e6 as cotistas_mm,
  round(t.median_yield, 2) as median_yield_pct
from spine sp
cross join classes c
left join t
  on date_trunc('month', t.period)::date = sp.period
 and t.asset_class = c.asset_class
order by sp.period, c.asset_class
