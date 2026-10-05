-- Zero-row guard — see delinquency_trend.sql. This one is doubly exposed: it
-- inner-joins aging to mensal AND pins to one period, so it is empty
-- whenever the newest aging period has no matching mensal row. The fallback
-- emits one all-NULL row rather than failing the whole build.
-- The month is FIDC's latest COMPLETE one, not the latest filed one: on
-- 2026-10-05 the newest month, 2026-09-30, held 428 early filings against
-- ~4,400, so max(period) would rank the early filers alone. least() keeps a
-- cold database on max(period); MATERIALIZED so the clamp runs once.
with anchor as materialized (
  select least(
           latest_complete_period('fidc'),
           (select max(period) from cvm_fidc_aging)
         ) as p
),
ranked as (
  select
    a.cnpj,
    coalesce(r.fund_name, a.cnpj)                                        as fund_name,
    a.period,
    round(100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0), 1)       as delinquency_num1,
    a.vl_total_inad / 1e6                                                as inad_mm,
    m.vl_patrim_liq / 1e6                                                as pl_mm
  from cvm_fidc_aging a
  join cvm_fidc_mensal m using (cnpj, period)
  left join cvm_fund_registry r on r.cnpj = a.cnpj and r.entity_type = 'fidc'
  where a.period = (select an.p from anchor an)
    and m.vl_patrim_liq > 1e6
  order by delinquency_num1 desc nulls last
  limit 20
)
select cnpj, fund_name, period, delinquency_num1, inad_mm, pl_mm
from ranked
union all
select null::text, null::text, null::date, null::numeric, null::numeric, null::numeric
where not exists (select 1 from ranked)
order by delinquency_num1 desc nulls last
