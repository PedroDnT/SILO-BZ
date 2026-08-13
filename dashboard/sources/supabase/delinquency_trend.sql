-- Zero-row guard: the aggregate below inner-joins cvm_fidc_aging to
-- cvm_fidc_mensal and windows to 24 months, so a thin or late FIDC slice makes
-- it empty — and an empty source is a 0-byte parquet that kills the WHOLE
-- dashboard build ("File 'supabase_delinquency_trend.parquet' too small to be a
-- Parquet file"), not just this page. The union-all fallback emits one all-NULL
-- row only when the aggregate found nothing, so "no data" renders as no data
-- instead of taking the site down.
with agg as (
  select
    a.period,
    round(100.0 * sum(a.vl_total_inad) / nullif(sum(m.vl_patrim_liq), 0), 2) as delinquency_rate_pct,
    sum(a.vl_total_inad) / 1e6                                              as total_inad_mm,
    count(distinct a.cnpj)                                                  as n_funds
  from cvm_fidc_aging a
  join cvm_fidc_mensal m using (cnpj, period)
  where a.period >= current_date - interval '24 months'
  group by a.period
)
select period, delinquency_rate_pct, total_inad_mm, n_funds
from agg
union all
select null::date, null::numeric, null::numeric, null::bigint
where not exists (select 1 from agg)
order by period nulls last
