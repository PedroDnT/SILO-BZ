-- Top 20 administrators by AUM at the latest monthly period.
--
-- administrator_rankings() (src/store/analytical/14_ranking_functions.sql) joins
-- fact_fund_monthly to cvm_fund_registry and drops every fund whose admin_name
-- is NULL. Registry name coverage is sparse, so this function can legitimately
-- return NOTHING — and a 0-row source makes Evidence write a zero-byte parquet
-- that takes the entire build down.
--
-- The fix is structural, not cosmetic: a generate_series(1, 20) SLOT spine is
-- the row driver and the ranking is LEFT JOINed onto it. The source is always
-- exactly 20 rows; unfilled slots come back with a NULL name, which is the
-- truthful rendering of "the registry has no name at this rank". No placeholder
-- name is ever invented — mgr_coverage carries the coverage number itself.
--
-- PERIOD CHOICE, load-bearing: the function resolves a NULL period to
-- max(period) over fact_fund_monthly, and FIP is stored at 31-DEC of its
-- reporting year — a date that is in the FUTURE for most of the year. Passing
-- NULL would therefore pin the ranking to a FIP-only period and return nothing,
-- since FIP funds carry no registry admin/gestor name. An explicit period is
-- passed instead: the latest MONTHLY period (every family except FIP). A family
-- whose newest report is older than that month is simply not in it — the
-- function ranks one period and does not carry balances forward.
--
-- rank_pos from the function uses RANK() and can tie, so the join key is a
-- row_number over the returned set instead.
with ranked as (
  select
    row_number() over (order by rank_pos, admin_name) as slot,
    admin_name,
    period,
    n_funds,
    total_aum,
    net_flow,
    avg_yield,
    total_inadimpl
  from administrator_rankings(
    (select max(period) from fact_fund_monthly where entity_type <> 'fip'),
    'aum',
    20
  )
),
slots as (
  select generate_series(1, 20) as slot
)
select
  s.slot,
  r.admin_name,
  r.period,
  r.n_funds,
  r.total_aum      / 1e9 as aum_bn,
  r.net_flow       / 1e9 as net_flow_bn,
  r.total_inadimpl / 1e6 as inadimpl_mm,
  round(r.avg_yield, 2)  as avg_yield_num2
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
