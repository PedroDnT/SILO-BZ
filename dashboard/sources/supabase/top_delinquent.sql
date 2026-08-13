-- Zero-row guard — see delinquency_trend.sql. This one is doubly exposed: it
-- inner-joins aging to mensal AND pins to `max(period)`, so it is empty
-- whenever the newest aging period has no matching mensal row. The fallback
-- emits one all-NULL row rather than failing the whole build.
with ranked as (
  select
    a.cnpj,
    coalesce(r.fund_name, a.cnpj)                                        as fund_name,
    a.period,
    round(100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0), 1)       as delinquency_pct,
    a.vl_total_inad / 1e6                                                as inad_mm,
    m.vl_patrim_liq / 1e6                                                as pl_mm
  from cvm_fidc_aging a
  join cvm_fidc_mensal m using (cnpj, period)
  left join cvm_fund_registry r on r.cnpj = a.cnpj and r.entity_type = 'fidc'
  where a.period = (select max(period) from cvm_fidc_aging)
    and m.vl_patrim_liq > 1e6
  order by delinquency_pct desc nulls last
  limit 20
)
select cnpj, fund_name, period, delinquency_pct, inad_mm, pl_mm
from ranked
union all
select null::text, null::text, null::date, null::numeric, null::numeric, null::numeric
where not exists (select 1 from ranked)
order by delinquency_pct desc nulls last
