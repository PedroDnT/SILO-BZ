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
  -- latest_complete_period(null) fixes two bugs the old
  -- coalesce(max(period), ...) anchor had at once:
  --   1. it took max(period) with NO entity filter, and FIP files on Dec-31
  --      of the CURRENT year — so the 36-month window ended in the future
  --      and the right ~5 months of every /fund chart were empty by
  --      construction;
  --   2. it happily anchored on a partially-filed trailing month.
  -- The function never returns NULL (previous-month floor on a cold DB), so
  -- the zero-row spine guarantee is preserved.
  select latest_complete_period(null) as p_end
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
  -- entity_type passed through: search_funds('', null, 6) can return the same
  -- CNPJ under two entity types (dim_fund's PK is (cnpj, entity_type); a fund
  -- family sharing a registration CNPJ across e.g. fidc and fiagro is real,
  -- confirmed live). Without it, both rows pull the same fund_nav_series()
  -- output and render as a duplicated/zig-zagging line for one "fund".
  cross join lateral fund_nav_series(
    t.cnpj,
    (date_trunc('month', a.p_end) - interval '35 months')::date,
    current_date,
    t.entity_type
  ) n
  -- Per-family completeness clamp (raw-convention comparison: the bound for a
  -- month-end family is itself a month-end date). The lateral fetches to
  -- current_date and this filter, not the fetch window, decides what renders.
  where n.period <= latest_complete_period(t.entity_type)
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
-- date_trunc on the join key: FIDC/FIP periods are month-end / year-end and
-- never matched the first-of-month spine raw — a FIDC fund in the top 6
-- silently rendered no line at all.
left join series x on date_trunc('month', x.period)::date = m.period
order by m.period, x.fund
