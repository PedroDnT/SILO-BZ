-- FI portfolio allocation by asset type (tp_ativo) over the last 24 months,
-- from cvm_fi_cda. Long format: one row per (month, asset type).
--
-- WHAT cvm_fi_cda IS. CDA block 1 only: government bonds and repo, one row per
-- bond a fund holds. Its key is (cnpj, period, tp_fundo, tp_aplic, tp_ativo,
-- cd_isin, tp_negoc) since migration 49 (#348), and every year was re-ingested
-- under it (2026-09-27 and 09-28), so the sums here are sums of real rows, not
-- the last row written. It is not the whole fund book (stocks, quotas and
-- debentures live in other blocks and tables).
--
-- ZERO-ROW SAFETY: a 24-month generate_series spine drives the result and the
-- per-month breakdown is LEFT JOIN LATERAL'd on, so months with no CDA rows (and
-- an entirely empty cvm_fi_cda) still emit a row.
with monthly as (
  -- Funds with a CDA row, per month. CVM publishes the newest CDA months thin
  -- and fills them in over the following months (2026-06 held about 7.4k funds
  -- against about 11.9k in CVM's own file, issue #476), so the mix of a thin
  -- month is not comparable. Window bounded: the 12 months before each month
  -- are needed for the median below.
  select period, count(distinct cnpj) as n_funds
  from cvm_fi_cda
  where period >= (date_trunc('month', current_date) - interval '48 months')::date
  group by period
),
complete as (
  -- The last month whose funds reach 90% of the median of the 12 months before
  -- it: the rule /rates and /holdings use. No row (so NULL below) when no month qualifies.
  select m.period as p_complete
  from monthly m
  where m.n_funds >= 0.9 * (
    select percentile_cont(0.5) within group (order by p.n_funds)
    from monthly p
    where p.period <  m.period
      and p.period >= m.period - interval '12 months'
  )
  order by m.period desc
  limit 1
),
anchor as (
  -- SPINE END: the last ingested CDA month, capped at the last COMPLETE CDA
  -- month (above) and at the last COMPLETE FI month (mv_period_completeness).
  -- The newest ingested month is routinely only partly filed, and an anchor on
  -- max(period) alone drew it as a cliff. The FI cap is expressed as that
  -- month's LAST day so a month-end `period` and a first-of-month one both fall
  -- inside it. least() ignores NULLs: with no complete CDA month, or an empty
  -- table, the other bounds decide.
  select least(
           max(period),
           (select p_complete from complete),
           (date_trunc('month', latest_complete_period('fi')) + interval '1 month' - interval '1 day')::date
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
