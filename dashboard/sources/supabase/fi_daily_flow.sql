-- Daily industry subscription / redemption flow from cvm_fi_diario.
--
-- cvm_fi_diario is multi-GB and RANGE-partitioned on dt_comptc, so this query is
-- BOUNDED (a 120-day window) and AGGREGATED (one row per date, never raw rows).
-- The window end is taken from fact_fund_monthly (a small matview) rather than
-- max(dt_comptc) on the partitioned table itself, because dt_comptc carries only
-- a BRIN index — a max() over it would scan every partition. The literal window
-- lets Postgres prune to the one or two partitions that can match.
--
-- ZERO-ROW SAFETY: a generate_series day spine drives the result (weekdays only,
-- ~86 rows), with the aggregate LEFT JOINed on. Holidays and non-reporting days
-- come back NULL; the source is never empty.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_month
  from fact_fund_monthly
  where entity_type = 'fi'
),
win as (
  select
    (a.p_month + interval '1 month' - interval '1 day')::date            as d_end,
    (a.p_month + interval '1 month' - interval '1 day')::date - 119      as d_start
  from anchor a
),
days as (
  select generate_series(w.d_start, w.d_end, interval '1 day')::date as dt
  from win w
),
flow as (
  select
    d.dt_comptc                                                    as dt,
    sum(d.captc_dia) / 1e9                                         as inflow_bn,
    sum(d.resg_dia) / 1e9                                          as outflow_bn,
    sum(coalesce(d.captc_dia, 0) - coalesce(d.resg_dia, 0)) / 1e9  as net_flow_bn,
    sum(d.vl_patrim_liq) / 1e12                                    as aum_tn,
    count(*)                                                       as n_funds
  from cvm_fi_diario d
  cross join win w
  where d.dt_comptc between w.d_start and w.d_end
  group by d.dt_comptc
)
select
  s.dt                                                         as dt_comptc,
  f.inflow_bn                                                  as inflow_bn,
  f.outflow_bn                                                 as outflow_bn,
  f.net_flow_bn                                                as net_flow_bn,
  sum(coalesce(f.net_flow_bn, 0)) over (order by s.dt)         as cum_net_flow_bn,
  f.aum_tn                                                     as aum_tn,
  f.n_funds                                                    as n_funds
from days s
left join flow f on f.dt = s.dt
where extract(isodow from s.dt) < 6
order by s.dt
