-- Promised vs realised tranche performance across the FIDC universe, monthly.
--
-- Same median-over-mean reasoning as fidc_tranche_performance.sql: the CVM
-- pr_desemp_* fields carry dirty outliers (schema.sql documents values up to
-- 1.6e8), so a mean would be meaningless and a hard cut-off would be arbitrary.
--
-- ZERO-ROW SAFETY: generate_series over the last 24 calendar months drives the
-- rows; the aggregate is LEFT JOINed, so months FIDC has not published yet come
-- back NULL rather than shortening the result to nothing.
with anchor as (
  -- SPINE END: the last month the tranche filings have actually reached,
  -- capped at FIDC's completeness bound. That bound (mv_period_completeness)
  -- is measured on cvm_fidc_mensal, not on cvm_fidc_tranche, so the cap
  -- alone left the trailing months on the axis, empty. least() ignores a
  -- NULL max() on an empty table.
  select least(
           date_trunc('month', latest_complete_period('fidc')),
           date_trunc('month', max(period))
         )::date as p_end
  from cvm_fidc_tranche
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
agg as (
  select
    -- date_trunc is a no-op when period is already the competência first-of-month,
    -- and keeps the join to `months` correct if CVM ever files a mid-month
    -- DT_COMPTC (nothing in the ingest path normalises it).
    date_trunc('month', t.period)::date                                as period,
    count(*)                                                          as n_tranches,
    count(distinct t.cnpj)                                            as n_funds,
    round((percentile_cont(0.5) within group (order by t.pr_desemp_esperado))::numeric, 2) as esperado_median,
    round((percentile_cont(0.5) within group (order by t.pr_desemp_real))::numeric, 2)     as real_median,
    count(*) filter (
      where t.pr_desemp_real is not null
        and t.pr_desemp_esperado is not null
        and t.pr_desemp_real < t.pr_desemp_esperado
    )                                                                 as n_underperforming,
    count(*) filter (
      where t.pr_desemp_real is not null and t.pr_desemp_esperado is not null
    )                                                                 as n_comparable
  from cvm_fidc_tranche t
  cross join anchor x
  where t.period >= (date_trunc('month', x.p_end) - interval '23 months')::date
    and t.period <  (date_trunc('month', x.p_end) + interval '1 month')::date
  group by date_trunc('month', t.period)::date
)
select
  m.period,
  a.n_tranches,
  a.n_funds,
  a.esperado_median,
  a.real_median,
  round(a.real_median - a.esperado_median, 2)                       as gap_median,
  round(100.0 * a.n_underperforming / nullif(a.n_comparable, 0), 1) as underperforming_num1
from months m
left join agg a on a.period = m.period
order by m.period
