-- Reporting coverage: distinct funds present per month, per family, 24 months.
--
-- Wraps data_coverage() (src/store/analytical/09_analytical_functions.sql),
-- which counts distinct cnpj per (period, entity_type) in fact_fund_monthly.
-- This is the downstream half of pipeline health: the ingest log can say 'ok'
-- while the analytical layer still has a hole, and a month whose fund count
-- collapses is a data problem the log alone would not show.
--
-- Month spine drives the rows (fixed 24) with the function LEFT JOINed on, so an
-- empty fact_fund_monthly gives 24 blank months rather than a 0-row source —
-- the zero-byte parquet that breaks an Evidence build.
--
-- Expect structural gaps, not just failures: FIP reports yearly (only its
-- December month is populated), FIAGRO's monthly file only begins 2025-05, and
-- CVM publishes monthly datasets with a 1-2 month lag, so the newest month or
-- two are legitimately thin.
with anchor as (
  -- SPINE END: the last ENDED month any monthly family has reached. This page's
  -- job is to show the per-family lag, so a slow family's blank trailing month
  -- stays visible on purpose — but a month NO family has reached, or the
  -- in-progress month, is not drawn. FIP is excluded from the max because it is
  -- stored at 31-Dec of its reporting year, a date in the future for most of the
  -- calendar year.
  select least(
           date_trunc('month', current_date) - interval '1 month',
           date_trunc('month', max(period))
         )::date as p_end
  from fact_fund_monthly
  where entity_type <> 'fip'
),
spine as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
t as (
  select c.*
  from anchor a
  cross join lateral data_coverage(
    null,
    (date_trunc('month', a.p_end) - interval '23 months')::date,
    (date_trunc('month', a.p_end) + interval '1 month' - interval '1 day')::date
  ) c
)
select
  sp.period,
  sum(t.n_funds) filter (where t.entity_type = 'fi')     as fi_funds,
  sum(t.n_funds) filter (where t.entity_type = 'fidc')   as fidc_funds,
  sum(t.n_funds) filter (where t.entity_type = 'fii')    as fii_funds,
  sum(t.n_funds) filter (where t.entity_type = 'fiagro') as fiagro_funds,
  sum(t.n_funds) filter (where t.entity_type = 'fip')    as fip_funds,
  sum(t.n_funds)                                         as total_funds
from spine sp
left join t on date_trunc('month', t.period)::date = sp.period
group by sp.period
order by sp.period
