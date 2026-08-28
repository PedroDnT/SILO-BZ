-- Rebased cumulative return for the six largest funds, via
-- fund_performance_series() — the horizontal (through time) counterpart to the
-- rankings on /performance.
--
-- return_basis travels with every row and is NEVER conflated across families:
-- FI = quota return and FII = compounded dividend yield. FIDC/FIAGRO/FIP are
-- excluded because their PL growth mixes flows and capital calls with market
-- performance and therefore is not a return.
--
-- ZERO-ROW SAFETY: 36-month generate_series spine drives the output; the series
-- is LEFT JOINed on.
with anchor as (
  -- latest_complete_period(null): the old unfiltered max(period) anchored on
  -- FIP's current-year Dec-31 row, blanking the right ~5 months of the
  -- rebased-return chart; it also anchored on partially-filed months.
  select latest_complete_period(null) as p_end
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '35 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
top_funds as (
  select
    s.cnpj                        as cnpj,
    coalesce(s.fund_name, s.cnpj) as fund,
    s.entity_type                 as entity_type
  -- Only FI quota returns and FII dividend yield are return-like measures.
  -- PL growth for FIDC/FIAGRO/FIP is driven by flows and capital calls; drawing
  -- it on a return chart produced economically meaningless million-% lines.
  from search_funds('', null, 50) s
  where s.entity_type in ('fi', 'fii')
  order by s.latest_aum desc nulls last
  limit 6
),
series as (
  select
    t.fund                  as fund,
    p.cnpj                  as cnpj,
    p.period                as period,
    p.entity_type           as entity_type,
    p.asset_class           as asset_class,
    p.return_basis          as return_basis,
    p.period_return         as period_return,
    p.cumulative_return     as cumulative_return
  from top_funds t
  cross join anchor a
  -- entity_type passed through — same collision as fund_nav_series.sql: a
  -- CNPJ shared across two entity types would otherwise interleave two
  -- distinct funds' returns into one "fund" series and corrupt the rebase.
  cross join lateral fund_performance_series(
    t.cnpj,
    (date_trunc('month', a.p_end) - interval '35 months')::date,
    current_date,
    t.entity_type
  ) p
  -- per-family completeness clamp (raw-convention comparison)
  where p.period <= latest_complete_period(t.entity_type)
)
select
  m.period                              as period,
  x.fund                                as fund,
  x.entity_type                         as entity_type,
  x.asset_class                         as asset_class,
  x.return_basis                        as return_basis,
  round(x.period_return * 100, 2)       as period_return_num2,
  round(x.cumulative_return * 100, 2)   as cum_return_num2
from months m
-- date_trunc on the join key: month-end/year-end family periods never
-- matched the first-of-month spine raw (see fund_nav_series.sql)
left join series x on date_trunc('month', x.period)::date = m.period
order by m.period, x.fund
