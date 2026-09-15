-- FIP net assets at the latest complete year-end, for the home-page tile.
-- FIP files yearly (fact_fund_monthly keys it 31-Dec of the filing year), so
-- it is shown as a number beside the 12-month stacked area rather than as a
-- one-month band inside it. An aggregate with no GROUP BY always returns a row.
select
  max(period)                 as period,
  sum(vl_patrim_liq) / 1e9    as aum_bn,
  count(*)                    as n_funds
from fact_fund_monthly
where entity_type = 'fip'
  and period = (
    select max(period) from fact_fund_monthly
    where entity_type = 'fip' and period <= latest_complete_period('fip')
  )
