-- /holdings: the largest holdings on each kind's last complete CDA month
-- (completeness as in holdings_monthly.sql), from mv_fund_holdings_monthly.
--
-- One source, three grains, told apart by `grain`:
--   'stock'          the 25 tickers funds hold the most of, by R$, with the
--                    same ticker 12 months earlier
--   'stock_related'  the 15 tickers with the most R$ held by funds of the
--                    issuer's own economic group (emissor_ligado = 'S')
--   'debenture'      the 25 debenture issuers (B3 code from the ISIN) funds
--                    hold the most of, by R$, 12 months earlier alongside
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the result.
with tot as (
  select kind, period, n_funds
  from mv_fund_holdings_monthly
  where key is null
),
anchor as (
  select m.kind, max(m.period) as p_end
  from tot m
  where m.n_funds >= 0.9 * (
    select percentile_cont(0.5) within group (order by p.n_funds)
    from tot p
    where p.kind = m.kind
      and p.period <  m.period
      and p.period >= m.period - interval '12 months'
  )
  group by m.kind
),
cur as (
  select h.kind, h.key, h.n_funds, h.n_assets, h.vl_total, h.vl_related, h.period
  from mv_fund_holdings_monthly h
  join anchor a on a.kind = h.kind and h.period = a.p_end
  where h.key is not null
),
prev as (
  select h.kind, h.key, h.vl_total
  from mv_fund_holdings_monthly h
  join anchor a on a.kind = h.kind
   and h.period = (a.p_end - interval '12 months')::date
  where h.key is not null
),
ranked as (
  select
    c.*,
    p.vl_total as vl_total_12m_ago,
    row_number() over (partition by c.kind order by c.vl_total desc nulls last)   as rk_total,
    row_number() over (partition by c.kind order by c.vl_related desc nulls last) as rk_related
  from cur c
  left join prev p on p.kind = c.kind and p.key = c.key
),
result as (
  select
    case kind when 'stock' then 'stock' else 'debenture' end as grain,
    key, period, n_funds, n_assets,
    vl_total / 1e9          as held_bn,
    vl_total_12m_ago / 1e9  as held_12m_ago_bn,
    vl_related / 1e9        as related_bn,
    rk_total                as rk
  from ranked
  where rk_total <= 25
  union all
  select
    'stock_related', key, period, n_funds, n_assets,
    vl_total / 1e9, vl_total_12m_ago / 1e9, vl_related / 1e9, rk_related
  from ranked
  where kind = 'stock' and rk_related <= 15 and vl_related > 0
)
select r.*
from (select 1) as one
left join result r on true
order by r.grain, r.rk
