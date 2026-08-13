-- FI portfolio allocation by asset type (tp_ativo) over the last 24 months,
-- from cvm_fi_cda. Long format: one row per (month, asset type).
--
-- READ THIS BEFORE TRUSTING THE LEVELS. cvm_fi_cda's natural key is
-- (cnpj, period, tp_aplic, tp_ativo) and the ingest upserts ON CONFLICT DO
-- UPDATE, so the many security-level rows a fund reports inside one
-- (tp_aplic, tp_ativo) bucket collapse to the LAST one written — they are not
-- summed. The shape of the mix is therefore directional; the absolute R$ totals
-- are a lower bound on the real book, not a market-value census. The page says
-- this next to the chart. Nothing here is scaled up to "fix" it.
--
-- ZERO-ROW SAFETY: a 24-month generate_series spine drives the result and the
-- per-month breakdown is LEFT JOIN LATERAL'd on, so months with no CDA rows (and
-- an entirely empty cvm_fi_cda) still emit a row.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_end
  from cvm_fi_cda
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
alloc as (
  select
    c.period            as period,
    c.tp_ativo          as tp_ativo,
    sum(c.vl_merc_pos_final) as v
  from cvm_fi_cda c
  cross join anchor a
  where c.period between (date_trunc('month', a.p_end) - interval '23 months')::date
                     and a.p_end
  group by c.period, c.tp_ativo
),
top_types as (
  select tp_ativo
  from alloc
  where tp_ativo is not null
  group by tp_ativo
  order by sum(v) desc nulls last
  limit 8
)
select
  m.period                                            as period,
  coalesce(x.asset_type, 'no CDA rows in window')     as asset_type,
  x.value_bn                                          as value_bn
from months m
left join lateral (
  select
    case
      when a.tp_ativo is null then 'Unclassified'
      when a.tp_ativo in (select tp_ativo from top_types) then a.tp_ativo
      else 'Other asset types'
    end             as asset_type,
    sum(a.v) / 1e9  as value_bn
  from alloc a
  where a.period = m.period
  group by 1
) x on true
order by m.period, x.value_bn desc nulls last
