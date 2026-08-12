select
  period,
  percentile_cont(0.10) within group (order by pct_dividend_yield_mes) * 100 as p10,
  percentile_cont(0.25) within group (order by pct_dividend_yield_mes) * 100 as p25,
  percentile_cont(0.50) within group (order by pct_dividend_yield_mes) * 100 as median,
  percentile_cont(0.75) within group (order by pct_dividend_yield_mes) * 100 as p75,
  percentile_cont(0.90) within group (order by pct_dividend_yield_mes) * 100 as p90
from cvm_fii_mensal
where doc_subtype = 'complemento'
  and pct_dividend_yield_mes > 0
  and period >= current_date - interval '12 months'
group by period
order by period
