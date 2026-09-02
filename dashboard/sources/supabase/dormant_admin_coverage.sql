-- /dormant: how many screen hits carry a registry administrator name.
--
-- The by-administrator ranking can only rank what the registry names. This
-- publishes the size of what it cannot, so a short ranking is read as "the
-- registry is sparse" rather than "few administrators are involved".
--
-- ZERO-ROW SAFETY: no-GROUP-BY aggregate — always one row.
select
  count(*)                        as hits,
  count(admin_name)               as hits_with_admin,
  count(*) - count(admin_name)    as hits_without_admin
from fraud_screen_dormant_funds(3)
