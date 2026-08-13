-- Realised vs promised tranche performance at the latest reported period.
--
-- Reads vw_fidc_tranche_detail (src/store/analytical/07_vw_cross_domain.sql),
-- which already joins cvm_fidc_tranche to the fund's PL and delinquency.
--
-- MEDIAN, NOT MEAN — on purpose. Both the schema and the view carry an explicit
-- warning that these are raw CVM percentage fields containing garbage outliers
-- ("raw CVM has dirty values up to 1.6e8 … filter ABS(vl_rentab_mes) at
-- client"). A mean would be owned by those outliers; the median is robust
-- without needing an arbitrary cut-off that silently discards real rows.
-- n_tranches reports how many filings each figure rests on.
--
-- classe_serie is free text (TAB_X_CLASSE_SERIE), so it is folded into the four
-- structural tranche classes using the same senior/subordinated convention
-- fidc_subordination_trend() uses. Anything unrecognised lands in "Outras"
-- rather than being dropped.
--
-- Match is a SUBSTRING, not a prefix: CVM-175 (2025+) labels every senior
-- tranche "Subclasse Senior ..." / "Classe Sênior ...", which a prefix match
-- ('senior%') never catches — verified against a live CVM file, where it
-- matched 0 of ~10,700 rows. That bug is also why "Senior Quotas" showed as
-- zero on this page.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed to the grouped aggregate.
with latest as (
  select max(period) as period from cvm_fidc_tranche
),
base as (
  select
    case
      when t.classe_serie ilike '%senior%' or t.classe_serie ilike '%sênior%'
        then 'Sênior'
      when t.classe_serie ilike '%mezanino%'
        then 'Mezanino'
      when t.classe_serie ilike '%subordinada%'
        or t.classe_serie ilike '%subordinado%'
        or t.classe_serie ilike '%junior%'
        or t.classe_serie ilike '%júnior%'
        then 'Júnior / Subordinada'
      else 'Outras'
    end                    as tranche_class,
    t.pr_desemp_esperado,
    t.pr_desemp_real,
    t.vl_rentab_mes,
    t.fund_pl,
    t.cnpj
  from vw_fidc_tranche_detail t
  join latest l on t.period = l.period
),
agg as (
  select
    tranche_class,
    count(*)                                                          as n_tranches,
    count(distinct cnpj)                                              as n_funds,
    count(*) filter (where pr_desemp_esperado is not null)            as n_with_esperado,
    count(*) filter (where pr_desemp_real is not null)                as n_with_real,
    round((percentile_cont(0.5) within group (order by pr_desemp_esperado))::numeric, 2) as desemp_esperado_median,
    round((percentile_cont(0.5) within group (order by pr_desemp_real))::numeric, 2)     as desemp_real_median,
    round((percentile_cont(0.5) within group (order by vl_rentab_mes))::numeric, 2)      as rentab_mes_median,
    count(*) filter (
      where pr_desemp_real is not null
        and pr_desemp_esperado is not null
        and pr_desemp_real < pr_desemp_esperado
    )                                                                 as n_underperforming,
    count(*) filter (
      where pr_desemp_real is not null and pr_desemp_esperado is not null
    )                                                                 as n_comparable,
    sum(fund_pl) / 1e9                                                as fund_pl_bn
  from base
  group by tranche_class
),
row_guard as (
  select 1 as one
)
select
  a.tranche_class,
  a.n_tranches,
  a.n_funds,
  a.desemp_esperado_median,
  a.desemp_real_median,
  round(a.desemp_real_median - a.desemp_esperado_median, 2)              as gap_median,
  a.rentab_mes_median,
  a.n_comparable,
  round(100.0 * a.n_underperforming / nullif(a.n_comparable, 0), 1)      as underperforming_pct
from row_guard g
left join agg a on true
order by a.n_tranches desc nulls last
