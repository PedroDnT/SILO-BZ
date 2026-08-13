-- FI investor mix over time (long format: one row per month per investor class),
-- from the nr_cotst_* split in cvm_fi_perfil (PERFIL_MENSAL).
--
-- PROVENANCE / COVERAGE: the seven nr_cotst_* columns exist on cvm_fi_perfil
-- (src/store/schema.sql, "typed-field lifts" block) but the perfil field map
-- (src/parsers/field_maps/fi_perfil.py) only maps cnpj / period / tp_fundo /
-- mod_var — every other CSV header lands in the residual `raw` JSONB. So each
-- class reads the typed column FIRST and falls back to the raw key that the CVM
-- header would produce. When neither is present the value is NULL — absent data
-- is shown as absent, never imputed.
--
-- ZERO-ROW SAFETY: a 24-month generate_series spine CROSS JOINed with a fixed
-- 7-row class list drives the output (168 rows, always), with the aggregate LEFT
-- JOINed on. An empty or unmapped cvm_fi_perfil yields NULL counts, not an empty
-- parquet.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_end
  from cvm_fi_perfil
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
classes (investor_class, sort_order, is_retail) as (
  values
    ('Individuals - private banking', 1, true),
    ('Corporates - retail',           2, true),
    ('Corporates - private banking',  3, false),
    ('Financial companies',           4, false),
    ('Banks (own book)',              5, false),
    ('Funds & investment clubs',      6, false),
    ('Distributors',                  7, false)
),
mix as (
  select
    p.period as period,
    sum(coalesce(p.nr_cotst_pf_pb::numeric,
        case when p.raw->>'NR_COTST_PF_PB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PF_PB')::numeric end))                   as pf_pb,
    sum(coalesce(p.nr_cotst_pj_nao_financ_varejo::numeric,
        case when p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO')::numeric end))    as pj_nao_financ_varejo,
    sum(coalesce(p.nr_cotst_pj_nao_financ_pb::numeric,
        case when p.raw->>'NR_COTST_PJ_NAO_FINANC_PB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_NAO_FINANC_PB')::numeric end))        as pj_nao_financ_pb,
    sum(coalesce(p.nr_cotst_pj_financ::numeric,
        case when p.raw->>'NR_COTST_PJ_FINANC' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_FINANC')::numeric end))               as pj_financ,
    sum(coalesce(p.nr_cotst_banco::numeric,
        case when p.raw->>'NR_COTST_BANCO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_BANCO')::numeric end))                   as banco,
    sum(coalesce(p.nr_cotst_fi_clube::numeric,
        case when p.raw->>'NR_COTST_FI_CLUBE' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_FI_CLUBE')::numeric end))                as fi_clube,
    sum(coalesce(p.nr_cotst_distrib::numeric,
        case when p.raw->>'NR_COTST_DISTRIB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_DISTRIB')::numeric end))                 as distrib
  from cvm_fi_perfil p
  cross join anchor a
  where p.period between (date_trunc('month', a.p_end) - interval '23 months')::date
                     and a.p_end
  group by p.period
)
select
  m.period          as period,
  c.investor_class  as investor_class,
  c.sort_order      as sort_order,
  case c.sort_order
    when 1 then x.pf_pb
    when 2 then x.pj_nao_financ_varejo
    when 3 then x.pj_nao_financ_pb
    when 4 then x.pj_financ
    when 5 then x.banco
    when 6 then x.fi_clube
    when 7 then x.distrib
  end / 1e3         as holders_k
from months m
cross join classes c
left join mix x on x.period = m.period
order by m.period, c.sort_order
