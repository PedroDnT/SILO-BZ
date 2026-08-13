-- Investor growth by conformed asset class, monthly, last 24 months.
--
-- Wraps quotaholder_trend_by_class()
-- (src/store/analytical/14_ranking_functions.sql). Month spine CROSS JOINed to
-- the literal class list drives the row count (fixed 24 x 9 = 216) with the
-- function LEFT JOINed, so the source cannot come back empty and write the
-- zero-byte parquet that breaks an Evidence build.
--
-- COVERAGE: only classes whose underlying table carries nr_cotst can appear at
-- all — FI (Fixed Income / Equity / Multimarket / Other FI), Real Estate and
-- Agribusiness. Structured Credit (FIDC) and Private Equity (FIP) report no
-- quotaholder count in CVM's files, so they are blank by construction.
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
  from quotaholder_trend_by_class(
    (date_trunc('month', current_date) - interval '23 months')::date,
    current_date
  )
)
select
  sp.period,
  c.asset_class,
  t.total_cotistas / 1e6 as cotistas_mm,
  round(t.avg_cotistas_per_fund, 1) as avg_cotistas_per_fund,
  t.n_funds_with_data
from spine sp
cross join classes c
left join t
  on date_trunc('month', t.period)::date = sp.period
 and t.asset_class = c.asset_class
order by sp.period, c.asset_class
