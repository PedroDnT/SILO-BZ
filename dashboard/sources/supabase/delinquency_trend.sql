select
  a.period,
  round(100.0 * sum(a.vl_total_inad) / nullif(sum(m.vl_patrim_liq), 0), 2) as delinquency_rate_pct,
  sum(a.vl_total_inad) / 1e6 as total_inad_mm,
  count(distinct a.cnpj) as n_funds
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
where a.period >= current_date - interval '24 months'
group by a.period
order by a.period
