-- Honest coverage counter for the PERFIL_MENSAL-derived sections of /fi.
--
-- The nr_cotst_* / pr_patrim_liq_maior_cotst columns are declared in schema.sql
-- but NOT mapped by src/parsers/field_maps/fi_perfil.py, so they normally sit in
-- the residual `raw` JSONB. This source counts how many funds actually resolve a
-- value (typed column OR raw key) at the latest perfil period, so the page can
-- state what is present instead of implying coverage it does not have.
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
  count(*) filter (
    where coalesce(p.pr_patrim_liq_maior_cotst::numeric,
      case when p.raw->>'PR_PATRIM_LIQ_MAIOR_COTST' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PATRIM_LIQ_MAIOR_COTST', ',', '.')::numeric end) is not null
  )                                                                      as funds_with_holder_share,
  (select count(*) from cvm_fi_cda c where c.period = (select max(period) from cvm_fi_cda))
                                                                         as cda_rows_latest_period,
  (select max(period) from cvm_fi_cda)                                   as cda_latest_period
from anchor a
left join cvm_fi_perfil p on p.period = a.p_end
group by a.p_end
