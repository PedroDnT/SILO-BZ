-- /dormant: the empty shells — filing every month, zero flow, zero investors.
--
-- ZERO-ROW SAFETY: a generate_series(1, 100) SLOT spine is the row driver and
-- the screen's shells are LEFT JOINed onto it (the mgr_admin_rankings.sql
-- pattern). The source is always exactly 100 rows; unfilled slots carry NULLs.
-- The page filters `where cnpj is not null` in DuckDB, so the reader sees only
-- real hits — but the parquet can never be empty. 100 is a display cap, not a
-- count: the headline tile carries the true total.
with ranked as (
  select
    row_number() over (order by last_pl desc nulls last, fund_name, cnpj) as slot,
    cnpj,
    fund_name,
    admin_name,
    months_observed,
    last_pl
  from fraud_screen_dormant_funds(3)
  where dormancy = 'empty_shell'
),
slots as (
  select generate_series(1, 100) as slot
)
select
  s.slot,
  r.cnpj,
  r.fund_name,
  r.admin_name,
  r.months_observed,
  r.last_pl / 1e6 as last_pl_mm
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
