-- Administrators ranked by NET FLOW at the latest monthly period — who gathered
-- and who lost money in the month, as opposed to who is simply large.
--
-- Same function as the AUM table, called with p_metric = 'net_flow'
-- (src/store/analytical/14_ranking_functions.sql), and the same slot-spine
-- guarantee: 15 rows always, unfilled slots blank, because a 0-row source writes
-- a zero-byte parquet and kills the Evidence build.
--
-- PERIOD CHOICE: the latest MONTHLY period is passed explicitly rather than
-- NULL, because a NULL resolves to max(period) over fact_fund_monthly, which is
-- FIP's 31-DEC mapping — a future date in which nothing here can rank. See
-- mgr_admin_rankings for the full note.
--
-- net_flow = captc_mes − resg_mes summed over the administrator's funds. Those
-- two columns exist only for FI in fact_fund_monthly, so this ranks
-- administrators on their FI book alone; an administrator whose funds are all
-- FII/FIDC/FIP shows a blank or zero flow meaning "not reported", not "flat".
-- Ranking is descending, so outflows sit at the bottom of the table.
with ranked as (
  select
    row_number() over (order by rank_pos, admin_name) as slot,
    admin_name,
    period,
    n_funds,
    total_aum,
    net_flow
  from administrator_rankings(
    (select max(period) from fact_fund_monthly where entity_type <> 'fip'),
    'net_flow',
    15
  )
),
slots as (
  select generate_series(1, 15) as slot
)
select
  s.slot,
  r.admin_name,
  r.period,
  r.n_funds,
  r.net_flow  / 1e9 as net_flow_bn,
  r.total_aum / 1e9 as aum_bn,
  round(100.0 * r.net_flow / nullif(r.total_aum, 0), 2) as flow_over_aum_num2
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
