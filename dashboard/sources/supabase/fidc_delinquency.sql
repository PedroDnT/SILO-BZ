select
  a.period,
  round(100.0 * sum(a.vl_total_inad) / nullif(sum(m.vl_patrim_liq), 0), 2) as delinquency_rate_pct
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
where a.period >= current_date - interval '12 months'
group by a.period
order by a.period
