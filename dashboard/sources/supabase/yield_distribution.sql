-- pct_dividend_yield_mes is CVM's Percentual_Dividend_Yield_Mes stored AS PUBLISHED,
-- i.e. already a percent (the API's `yield` metric documents it the same way).
-- An earlier version multiplied by 100 and the p90 line read ~2,000 %.
select
  period,
  percentile_cont(0.10) within group (order by pct_dividend_yield_mes) as p10,
  percentile_cont(0.25) within group (order by pct_dividend_yield_mes) as p25,
  percentile_cont(0.50) within group (order by pct_dividend_yield_mes) as median,
  percentile_cont(0.75) within group (order by pct_dividend_yield_mes) as p75,
  percentile_cont(0.90) within group (order by pct_dividend_yield_mes) as p90
from cvm_fii_mensal
where doc_subtype = 'complemento'
  and pct_dividend_yield_mes > 0
  and period >= current_date - interval '12 months'
  -- completeness clamp (mv_period_completeness)
  and period <= latest_complete_period('fii')
group by period
order by period
