-- /markets: the 15 largest weights in B3's IBOV theoretical portfolio on the
-- latest reference date held, from b3_index_portfolio (B3 BDI). participacao_pct
-- is B3's published weight, in percent. History only starts 2026-09-16 (B3
-- publishes no archive), so this is a snapshot, not a series.
--
-- ZERO-ROW SAFETY: a 1..15 rank driver fixes the row count; the portfolio is
-- LEFT JOINed on, so an empty table yields NULLs, never a 0-row source.
with last_ref as (
  select max(reference_date) as d
  from b3_index_portfolio
  where index_code = 'IBOV'
),
ranked as (
  select
    p.reference_date,
    p.codneg,
    p.asset_name,
    p.b3_sector,
    p.participacao_pct,
    row_number() over (order by p.participacao_pct desc, p.codneg) as rnk
  from b3_index_portfolio p
  join last_ref l on p.reference_date = l.d
  where p.index_code = 'IBOV'
)
select
  r.rnk                as rank,
  k.reference_date,
  k.codneg,
  k.asset_name,
  k.b3_sector,
  k.participacao_pct   as weight_num2
from generate_series(1, 15) as r(rnk)
left join ranked k on k.rnk = r.rnk
order by r.rnk
