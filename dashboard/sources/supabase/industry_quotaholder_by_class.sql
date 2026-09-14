-- Investor growth by conformed asset class, monthly, last 24 months.
--
-- Wraps quotaholder_trend_by_class()
-- (src/store/analytical/14_ranking_functions.sql). Month spine CROSS JOINed to
-- the literal class list drives the row count (fixed 24 x 9 = 216) with the
-- function LEFT JOINed, so the source cannot come back empty and write the
-- zero-byte parquet that breaks an Evidence build.
--
-- COVERAGE: only classes whose underlying table carries nr_cotst can appear at
-- all. Measured on production 2026-08-28, per family, over all 2.3M
-- fact_fund_monthly rows:
--
--   fi      2,052,406 rows   100.0% carry nr_cotst
--   fii        72,478 rows    99.9%
--   fidc      178,237 rows     0.0%
--   fip        13,293 rows     0.0%
--   fiagro      2,494 rows     0.0%
--
-- So Fixed Income / Equity / Multimarket / Other FI and Real Estate populate;
-- Structured Credit (FIDC), Private Equity (FIP) and **Agribusiness (FIAGRO)**
-- are blank by construction — CVM's files for those families carry no
-- quotaholder count. Agribusiness was listed here as populated and is not; the
-- figures above are what the tables actually hold, not what the doc assumed.
-- A blank in those rows is the source being silent, never a load failure.
with anchor as (
  -- SPINE END: the last COMPLETE FI month (mv_period_completeness), never the
  -- in-progress month and never a partially filed one. FI is the family that
  -- populates this chart (COVERAGE above); FII's own bound may trail it, in
  -- which case Real Estate is blank for the trailing month while the FI
  -- classes still carry the axis. See dashboard/README, "Spine rule".
  select latest_complete_period('fi') as p_end
),
spine as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
classes (asset_class) as (
  values
    ('Fixed Income'), ('Equity'), ('Multimarket'), ('Other FI'),
    ('Structured Credit'), ('Real Estate'), ('Agribusiness'),
    ('Private Equity'), ('Other')
),
t as (
  select f.*
  from anchor a
  cross join lateral quotaholder_trend_by_class(
    (date_trunc('month', a.p_end) - interval '23 months')::date,
    (date_trunc('month', a.p_end) + interval '1 month' - interval '1 day')::date
  ) f
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
