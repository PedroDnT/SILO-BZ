-- /etf: ETF net assets and monthly net flows split into fixed income and
-- equity, from ANBIMA's bulletin (anbima_etf_class_monthly, level 'type':
-- 'ETF Renda Fixa' and 'ETF Renda Variável', R$ million). ANBIMA's split
-- starts 2025-01 in this table, so the series does too.
--
-- ZERO-ROW SAFETY: a month spine from 2025-01 to the last month held (2025-01
-- if none) drives the row count; the bulletin is LEFT JOINed on, so a missing
-- month reads as a blank, never a 0-row source.
with bounds as (
  select coalesce(max(reference_date), date '2025-01-01') as last_month
  from anbima_etf_class_monthly
  where level = 'type'
),
spine as (
  select generate_series(date '2025-01-01', b.last_month, interval '1 month')::date as period
  from bounds b
),
typed as (
  select reference_date, anbima_type_name, metric, value
  from anbima_etf_class_monthly
  where level = 'type'
    and metric in ('pl_brl_mm', 'captacao_liquida_brl_mm')
)
select
  s.period,
  max(t.value) filter (where t.anbima_type_name = 'ETF Renda Fixa'
                         and t.metric = 'pl_brl_mm') / 1000                 as pl_fixed_income_bn,
  max(t.value) filter (where t.anbima_type_name = 'ETF Renda Variável'
                         and t.metric = 'pl_brl_mm') / 1000                 as pl_equity_bn,
  max(t.value) filter (where t.anbima_type_name = 'ETF Renda Fixa'
                         and t.metric = 'captacao_liquida_brl_mm') / 1000   as flow_fixed_income_bn,
  max(t.value) filter (where t.anbima_type_name = 'ETF Renda Variável'
                         and t.metric = 'captacao_liquida_brl_mm') / 1000   as flow_equity_bn
from spine s
left join typed t on t.reference_date = s.period
group by s.period
order by s.period
