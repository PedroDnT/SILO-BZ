-- Individual tranches that missed their promised performance at the latest
-- reported period, largest funds first.
--
-- Grain is one row per (fund, classe_serie) — the literal TAB_X_CLASSE_SERIE
-- label as filed, not a normalised class, so the specific series is
-- identifiable.
--
-- OUTLIER BAND, stated rather than hidden: schema.sql warns that the raw CVM
-- pr_desemp_* fields "contain garbage outliers" (documented up to 1.6e8), and
-- one such row would otherwise occupy the whole table. Rows are therefore
-- restricted to |pr_desemp_*| <= 1000 (percent). This is a display filter, not
-- a correction — nothing is rescaled or coerced, and n_excluded_outliers on
-- every row reports how many latest-period tranche filings the band removed, so
-- the cost of the filter is always on screen.
--
-- Ordering is by fund PL, not by gap size: sorting by worst gap would rank the
-- dirtiest surviving numbers to the top rather than the most consequential.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed with ON TRUE — a period in
-- which no tranche underperformed still yields a row.
with latest as (
  select max(period) as period from cvm_fidc_tranche
),
scoped as (
  select
    t.cnpj,
    t.classe_serie,
    t.period,
    t.vl_cota,
    t.qt_cota,
    t.pr_desemp_esperado,
    t.pr_desemp_real,
    t.vl_rentab_mes,
    t.fund_pl,
    t.fund_inadimpl,
    abs(t.pr_desemp_esperado) <= 1000 and abs(t.pr_desemp_real) <= 1000 as in_band
  from vw_fidc_tranche_detail t
  join latest l on t.period = l.period
  where t.pr_desemp_esperado is not null
    and t.pr_desemp_real is not null
),
excluded as (
  select count(*) filter (where not in_band) as n_excluded_outliers
  from scoped
),
under as (
  select
    s.cnpj,
    s.classe_serie,
    s.period,
    s.pr_desemp_esperado,
    s.pr_desemp_real,
    s.vl_rentab_mes,
    s.fund_pl,
    s.fund_inadimpl
  from scoped s
  where s.in_band
    and s.pr_desemp_real < s.pr_desemp_esperado
  order by s.fund_pl desc nulls last
  limit 25
),
row_guard as (
  select 1 as one
)
select
  coalesce(r.fund_name, u.cnpj)                                as fund_name,
  u.cnpj,
  u.classe_serie,
  u.period,
  u.fund_pl / 1e6                                              as pl_mm,
  u.pr_desemp_esperado                                         as desemp_esperado,
  u.pr_desemp_real                                             as desemp_real,
  round(u.pr_desemp_real - u.pr_desemp_esperado, 2)            as gap,
  u.vl_rentab_mes                                              as rentab_mes,
  round(100.0 * u.fund_inadimpl / nullif(u.fund_pl, 0), 1)     as inadimpl_num1,
  e.n_excluded_outliers
from row_guard g
left join under u on true
left join excluded e on true
left join cvm_fund_registry r
  on r.cnpj = u.cnpj and r.entity_type = 'fidc'
order by u.fund_pl desc nulls last
