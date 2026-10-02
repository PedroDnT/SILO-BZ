-- Top 20 application types (tp_aplic) in the FI industry book at the latest
-- COMPLETE CDA period, with each one's share of the observed CDA total.
--
-- cvm_fi_cda is CDA block 1 only (government bonds and repo), one row per bond
-- since migration 49 (#348), so the values are sums of real rows. Shares are
-- explicitly "share of the observed CDA total", not "share of industry AUM".
--
-- ZERO-ROW SAFETY: `total` is an aggregate without GROUP BY (always one row) and
-- the breakdown is LEFT JOINed onto it, so an empty cvm_fi_cda yields one
-- all-NULL row instead of an empty parquet.
with monthly as (
  -- Funds with a CDA row, per month. CVM publishes the newest CDA months thin
  -- and fills them in later (2026-06 held about 7.4k funds against about 11.9k
  -- in CVM's own file, issue #476), so a thin month is not the latest period.
  select period, count(distinct cnpj) as n_funds
  from cvm_fi_cda
  where period >= (date_trunc('month', current_date) - interval '48 months')::date
  group by period
),
complete as (
  -- The last month whose funds reach 90% of the median of the 12 months before
  -- it: the rule /rates and /holdings use. No row (so NULL below) when no month qualifies.
  select m.period as p_complete
  from monthly m
  where m.n_funds >= 0.9 * (
    select percentile_cont(0.5) within group (order by p.n_funds)
    from monthly p
    where p.period <  m.period
      and p.period >= m.period - interval '12 months'
  )
  order by m.period desc
  limit 1
),
bound as materialized (
  -- ONE evaluation of latest_complete_period('fi'). The function is STABLE, so
  -- the planner MAY hoist it out of a row filter -- but #231 measured exactly
  -- this call being evaluated per row inside a scan of 2.35M fact rows, so the
  -- single evaluation is pinned here rather than left to the planner. The cap
  -- is the earlier of the last complete FI month (as that month's last day) and
  -- the last complete CDA month; least() ignores a NULL, so with no complete
  -- CDA month the FI cap decides, as before.
  select least(
           (date_trunc('month', latest_complete_period('fi'))
              + interval '1 month' - interval '1 day')::date,
           (select p_complete from complete)
         ) as last_complete_day
),
anchor as (
  -- the latest CDA month AT OR BEFORE the cap above (the last complete FI month
  -- and the last complete CDA month): the newest ingested month is routinely
  -- only partly filed. p_end stays an actual stored period value, so the
  -- equality join below still matches.
  --
  -- ORDER BY period DESC LIMIT 1, NOT max(period) FILTER (...): an aggregate
  -- FILTER blocks Postgres's index MIN/MAX rewrite, so the FILTER form reads
  -- EVERY row of cvm_fi_cda -- the holdings book, the largest table this
  -- dashboard touches -- to find one date. This form walks idx_fi_cda_period
  -- (period DESC) and stops at the first qualifying row. Identical value.
  select coalesce(
           (select t.period
              from cvm_fi_cda t
             where t.period <= (select b.last_complete_day from bound b)
             order by t.period desc
             limit 1),
           date_trunc('month', current_date)::date
         ) as p_end
),
base as (
  select
    c.tp_aplic                as tp_aplic,
    sum(c.vl_merc_pos_final)  as v,
    count(distinct c.cnpj)    as n_funds
  from cvm_fi_cda c
  cross join anchor a
  where c.period = a.p_end
  group by c.tp_aplic
  order by sum(c.vl_merc_pos_final) desc nulls last
  limit 20
),
total as (
  select
    (select p_end from anchor)                     as period,
    (select coalesce(sum(v), 0) from base)         as observed_total
)
select
  t.period                                                        as period,
  coalesce(b.tp_aplic, 'no CDA rows for this period')             as tp_aplic,
  b.v / 1e9                                                       as value_bn,
  round(100.0 * b.v / nullif(t.observed_total, 0), 1)             as share_num1,
  b.n_funds                                                       as n_funds
from total t
left join base b on true
order by b.v desc nulls last
