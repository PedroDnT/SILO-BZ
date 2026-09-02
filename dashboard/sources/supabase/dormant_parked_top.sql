-- /dormant: the largest parked-capital funds — investors present, nothing moving.
--
-- ZERO-ROW SAFETY: generate_series(1, 25) slot spine, screen LEFT JOINed; the
-- page filters `where cnpj is not null`. Ranked by net assets because the point
-- of this table is how much money is standing still, not how many vehicles.
with ranked as (
  select
    row_number() over (order by last_pl desc nulls last, fund_name, cnpj) as slot,
    cnpj,
    fund_name,
    admin_name,
    max_investors,
    last_pl
  from fraud_screen_dormant_funds(3)
  where dormancy = 'parked_capital'
),
slots as (
  select generate_series(1, 25) as slot
)
select
  s.slot,
  r.cnpj,
  r.fund_name,
  r.admin_name,
  r.max_investors,
  r.last_pl / 1e6 as last_pl_mm
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
