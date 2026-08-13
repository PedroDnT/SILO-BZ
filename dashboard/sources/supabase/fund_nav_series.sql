-- Net-assets and quota history for the six largest funds, via fund_nav_series().
--
-- The RPC needs a CNPJ, so it is driven from a bounded set (top 6 by latest net
-- assets) rather than the whole universe — 6 funds x 36 months keeps the parquet
-- tiny. Quota value is FI-only in fact_fund_monthly and stays NULL for the other
-- families; that is a real gap, not a zero.
--
-- ZERO-ROW SAFETY: a 36-month generate_series spine drives the output and the
-- series is LEFT JOINed on, so the source returns at least 36 rows even if
-- search_funds finds nothing.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_end
  from fact_fund_monthly
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '35 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
top_funds as (
  select
    s.cnpj                        as cnpj,
    coalesce(s.fund_name, s.cnpj) as fund,
    s.entity_type                 as entity_type
  from search_funds('', null, 6) s
),
series as (
  select
    t.fund              as fund,
    t.cnpj              as cnpj,
    t.entity_type       as entity_type,
    n.period            as period,
    n.vl_patrim_liq     as vl_patrim_liq,
    n.vl_quota          as vl_quota,
    n.nr_cotst          as nr_cotst
  from top_funds t
  cross join anchor a
  cross join lateral fund_nav_series(
    t.cnpj,
    (date_trunc('month', a.p_end) - interval '35 months')::date,
    a.p_end
  ) n
)
select
  m.period                  as period,
  x.fund                    as fund,
  x.cnpj                    as cnpj,
  x.entity_type             as entity_type,
  x.vl_patrim_liq / 1e9     as aum_bn,
  x.vl_quota                as quota,
  x.nr_cotst                as investors
from months m
left join series x on x.period = m.period
order by m.period, x.fund
