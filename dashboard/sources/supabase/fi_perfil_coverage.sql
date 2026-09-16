-- Honest coverage counter for the PERFIL_MENSAL-derived sections of /fi.
--
-- Migration 14 + the extended src/parsers/field_maps/fi_perfil.py lift all 16
-- NR_COTST_* buckets, all 16 PR_PL_COTST_* share-of-PL fields, the comitente
-- concentration block and the liquidity block into typed columns. Months
-- ingested BEFORE that change still hold those values only in the residual
-- `raw` JSONB, so every counter below reads coalesce(typed, raw->>'HEADER') and
-- the *_typed counters show how much of the latest period has actually been
-- re-ingested. The page can then state what is present instead of implying
-- coverage it does not have.
--
-- ZERO-ROW SAFETY: aggregate without GROUP BY over a one-row anchor → exactly
-- one row, always.
with bound as materialized (
  -- ONE evaluation of latest_complete_period('fi'). The function is STABLE, so
  -- the planner MAY hoist it out of a row filter -- but #231 measured exactly
  -- this call being evaluated per row inside a scan of 2.35M fact rows, so the
  -- single evaluation is pinned here rather than left to the planner.
  select (date_trunc('month', latest_complete_period('fi'))
          + interval '1 month' - interval '1 day')::date as last_complete_day
),
anchor as (
  -- the latest PERFIL month AT OR BEFORE the last complete FI month, so the
  -- coverage figure is never quoted on a partly filed newest month. p_end
  -- stays an actual stored period value (month end), so the equality join
  -- below still matches.
  --
  -- ORDER BY period DESC LIMIT 1, NOT max(period) FILTER (...): an aggregate
  -- FILTER blocks Postgres's index MIN/MAX rewrite, so the FILTER form reads
  -- EVERY row of cvm_fi_perfil to find one date. This form walks
  -- idx_fi_perfil_period (period DESC) and stops at the first qualifying
  -- row. Identical value, bounded work.
  select coalesce(
           (select t.period
              from cvm_fi_perfil t
             where t.period <= (select b.last_complete_day from bound b)
             order by t.period desc
             limit 1),
           current_date
         ) as p_end
)
select
  a.p_end                                                                as latest_period,
  count(p.cnpj)                                                          as funds_reporting,
  count(*) filter (
    where coalesce(p.nr_cotst_pf_pb::numeric,
      case when p.raw->>'NR_COTST_PF_PB' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PF_PB')::numeric end) is not null
  )                                                                      as funds_with_investor_split,
  -- the mass-retail bucket, absent from the schema until migration 14
  count(*) filter (
    where coalesce(p.nr_cotst_pf_varejo::numeric,
      case when p.raw->>'NR_COTST_PF_VAREJO' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PF_VAREJO')::numeric end) is not null
  )                                                                      as funds_with_retail_bucket,
  -- share-of-PL by investor type (money, not headcount)
  count(*) filter (
    where coalesce(p.pr_pl_cotst_pf_varejo::numeric,
      case when p.raw->>'PR_PL_COTST_PF_VAREJO' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_PF_VAREJO', ',', '.')::numeric end) is not null
  )                                                                      as funds_with_pl_split,
  count(*) filter (
    where coalesce(p.pr_patrim_liq_maior_cotst::numeric,
      case when p.raw->>'PR_PATRIM_LIQ_MAIOR_COTST' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PATRIM_LIQ_MAIOR_COTST', ',', '.')::numeric end) is not null
  )                                                                      as funds_with_holder_share,
  count(*) filter (
    where coalesce(p.pr_comitente_1::numeric,
      case when p.raw->>'PR_COMITENTE_1' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_COMITENTE_1', ',', '.')::numeric end) is not null
  )                                                                      as funds_with_comitente_share,
  -- how much of the latest period is served from typed columns rather than raw:
  -- 0 means the month predates the field-map lift and is still read from JSONB
  count(*) filter (where p.nr_cotst_pf_varejo is not null)                as funds_typed_retail_bucket,
  count(*) filter (where p.pr_pl_cotst_pf_varejo is not null)             as funds_typed_pl_split,
  (select count(*) from cvm_fi_cda c where c.period = (select max(period) from cvm_fi_cda))
                                                                         as cda_rows_latest_period,
  (select max(period) from cvm_fi_cda)                                   as cda_latest_period
from anchor a
left join cvm_fi_perfil p on p.period = a.p_end
group by a.p_end
