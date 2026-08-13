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
with anchor as (
  select coalesce(max(period), current_date) as p_end
  from cvm_fi_perfil
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
