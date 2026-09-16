-- Resumo por janela — last session / 1 week / MTD / coverage-to-date.
--
-- NO "YTD" and NO "last 12M" column, on purpose. B3 keeps ~21 business days of
-- this table and publishes no archive, so a year-to-date figure could only be
-- computed over the fortnight SILO happens to hold and would be a YTD number in
-- name only. `coverage` is the honest version: the sum over everything captured,
-- with the window that produced it stated beside it.
with bounds as (
  select max(reference_date) as last_date from fact_investor_flow_daily
)
select
  f.investor_type,
  sum(f.net_brl_mil / 1e6) filter (where f.reference_date = b.last_date)          as last_day_bn,
  sum(f.net_brl_mil / 1e6) filter (where f.reference_date > b.last_date - 7)      as week_bn,
  sum(f.net_brl_mil / 1e6) filter (
    where date_trunc('month', f.reference_date) = date_trunc('month', b.last_date)
  )                                                                              as mtd_bn,
  sum(f.net_brl_mil / 1e6)                                                       as coverage_bn,
  min(f.reference_date)                                                          as coverage_from,
  max(f.reference_date)                                                          as coverage_to
from fact_investor_flow_daily f
cross join bounds b
where f.net_brl_mil is not null
group by f.investor_type
order by sum(f.net_brl_mil / 1e6) desc
