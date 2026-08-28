-- Zero-row guard: the aggregate below inner-joins cvm_fidc_aging to
-- cvm_fidc_mensal and windows to 24 months, so a thin or late FIDC slice makes
-- it empty — and an empty source is a 0-byte parquet that kills the WHOLE
-- dashboard build ("File 'supabase_delinquency_trend.parquet' too small to be a
-- Parquet file"), not just this page. The union-all fallback emits one all-NULL
-- row only when the aggregate found nothing, so "no data" renders as no data
-- instead of taking the site down.
with agg as (
  select
    -- date_trunc: cvm_fidc_aging periods are month-END (measured 2026-08-27:
    -- day-of-month is 28/30/31), while every sibling /fidc chart plots
    -- first-of-month. Grouping on the raw period drew this chart's x-axis one
    -- month-width off its neighbours.
    date_trunc('month', a.period)::date as period,
    round(100.0 * sum(a.vl_total_inad) / nullif(sum(m.vl_patrim_liq), 0), 2) as delinquency_rate_num1,
    sum(a.vl_total_inad) / 1e6                                              as total_inad_mm,
    count(distinct a.cnpj)                                                  as n_funds
  from cvm_fidc_aging a
  join cvm_fidc_mensal m using (cnpj, period)
  where a.period >= current_date - interval '24 months'
    -- Completeness clamp: a partially-filed trailing month summed only the
    -- funds that had reported, rendering as a fake collapse in delinquency.
    and a.period <= latest_complete_period('fidc')
  group by date_trunc('month', a.period)
)
select period, delinquency_rate_num1, total_inad_mm, n_funds
from agg
union all
select null::date, null::numeric, null::numeric, null::bigint
where not exists (select 1 from agg)
order by period nulls last
