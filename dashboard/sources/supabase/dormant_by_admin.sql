-- /dormant: parked capital and empty shells by administrator, top 20 by parked
-- net assets.
--
-- Registry admin_name is sparse (see managers.md); hits with no administrator
-- name are EXCLUDED here and COUNTED in dormant_admin_coverage.sql, so the gap
-- is published beside the ranking instead of hidden inside it. No name is ever
-- invented for an unnamed administrator.
--
-- ZERO-ROW SAFETY: generate_series(1, 20) slot spine, LEFT JOINed; the page
-- filters `where admin_name is not null`.
with by_admin as (
  select
    admin_name,
    count(*) filter (where dormancy = 'parked_capital')                    as parked_funds,
    count(*) filter (where dormancy = 'empty_shell')                       as empty_shells,
    sum(last_pl) filter (where dormancy = 'parked_capital') / 1e9          as parked_pl_bn
  from fraud_screen_dormant_funds(3)
  where admin_name is not null
  group by admin_name
),
ranked as (
  select
    row_number() over (order by parked_pl_bn desc nulls last, parked_funds desc, admin_name) as slot,
    admin_name,
    parked_funds,
    empty_shells,
    parked_pl_bn
  from by_admin
),
slots as (
  select generate_series(1, 20) as slot
)
select
  s.slot,
  r.admin_name,
  r.parked_funds,
  r.empty_shells,
  r.parked_pl_bn
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
