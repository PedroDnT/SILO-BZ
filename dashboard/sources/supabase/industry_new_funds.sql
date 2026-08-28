-- Fund formation: first-ever reporting month per fund, by family, 36 months.
--
-- Wraps new_funds_per_period() (src/store/analytical/09_analytical_functions.sql),
-- which counts dim_fund rows by their first_period. Pivoted onto a month spine
-- that drives the row count (fixed 36), so an empty dim_fund yields NULLs
-- instead of a 0-row source — the failure mode that writes a zero-byte parquet
-- and kills the Evidence build.
--
-- "New" here means first appearance in CVM's data, which is a proxy for launch:
-- a fund that existed before the ingested history starts will look new in the
-- first month of coverage. Read the earliest months with that in mind.
with spine as (
  select generate_series(
           date_trunc('month', latest_complete_period(null)) - interval '35 months',
           date_trunc('month', latest_complete_period(null)),
           interval '1 month'
         )::date as period
),
t as (
  select *
  from new_funds_per_period(
    null,
    (date_trunc('month', latest_complete_period(null)) - interval '35 months')::date,
    current_date
  )
  -- per-family completeness clamp (see mv_period_completeness)
  where period <= latest_complete_period(entity_type)
)
select
  sp.period,
  sum(t.n_new) filter (where t.entity_type = 'fi')     as fi_new,
  sum(t.n_new) filter (where t.entity_type = 'fidc')   as fidc_new,
  sum(t.n_new) filter (where t.entity_type = 'fii')    as fii_new,
  sum(t.n_new) filter (where t.entity_type = 'fiagro') as fiagro_new,
  sum(t.n_new) filter (where t.entity_type = 'fip')    as fip_new,
  sum(t.n_new)                                         as total_new
from spine sp
left join t on date_trunc('month', t.period)::date = sp.period
group by sp.period
order by sp.period
