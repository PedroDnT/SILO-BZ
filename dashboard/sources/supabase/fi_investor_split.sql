-- Retail vs institutional rotation in the FI investor base.
--
-- Retail  = individuals (private banking) + non-financial corporates (retail)
-- Instit. = corporates (private banking) + financial companies + banks
--           + funds/clubs + distributors
--
-- CAVEAT (stated on the page too): cvm_fi_perfil models seven nr_cotst_* buckets;
-- CVM's mass-retail individual bucket is NOT among the columns lifted into the
-- schema, so "retail" here is the modelled retail subset, not the whole retail
-- base. Same typed-column-then-raw-fallback read as fi_investor_mix.sql.
--
-- ZERO-ROW SAFETY: driven by a 24-month generate_series spine; the aggregate is
-- LEFT JOINed on, so the source always returns 24 rows.
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
per_fund as (
  select p.period as period, v.retail as retail, v.instit as instit, v.any_split as any_split
  from cvm_fi_perfil p
  cross join anchor a
  cross join lateral (
    select
      coalesce(p.nr_cotst_pf_pb::numeric,
        case when p.raw->>'NR_COTST_PF_PB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PF_PB')::numeric end)                    as c_pf_pb,
      coalesce(p.nr_cotst_pj_nao_financ_varejo::numeric,
        case when p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO')::numeric end)     as c_varejo,
      coalesce(p.nr_cotst_pj_nao_financ_pb::numeric,
        case when p.raw->>'NR_COTST_PJ_NAO_FINANC_PB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_NAO_FINANC_PB')::numeric end)         as c_pj_pb,
      coalesce(p.nr_cotst_pj_financ::numeric,
        case when p.raw->>'NR_COTST_PJ_FINANC' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_FINANC')::numeric end)                as c_financ,
      coalesce(p.nr_cotst_banco::numeric,
        case when p.raw->>'NR_COTST_BANCO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_BANCO')::numeric end)                    as c_banco,
      coalesce(p.nr_cotst_fi_clube::numeric,
        case when p.raw->>'NR_COTST_FI_CLUBE' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_FI_CLUBE')::numeric end)                 as c_clube,
      coalesce(p.nr_cotst_distrib::numeric,
        case when p.raw->>'NR_COTST_DISTRIB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_DISTRIB')::numeric end)                  as c_distrib
  ) c
  cross join lateral (
    select
      coalesce(c.c_pf_pb, 0) + coalesce(c.c_varejo, 0)                        as retail,
      coalesce(c.c_pj_pb, 0) + coalesce(c.c_financ, 0) + coalesce(c.c_banco, 0)
        + coalesce(c.c_clube, 0) + coalesce(c.c_distrib, 0)                   as instit,
      (c.c_pf_pb is not null or c.c_varejo is not null or c.c_pj_pb is not null
        or c.c_financ is not null or c.c_banco is not null
        or c.c_clube is not null or c.c_distrib is not null)                  as any_split
  ) v
  where p.period between (date_trunc('month', a.p_end) - interval '23 months')::date
                     and a.p_end
),
agg as (
  select
    period                                            as period,
    sum(retail)                                       as retail,
    sum(instit)                                       as instit,
    count(*)                                          as n_funds,
    count(*) filter (where any_split)                 as n_funds_with_split
  from per_fund
  group by period
)
select
  m.period                                                          as period,
  a.retail / 1e3                                                    as retail_k,
  a.instit / 1e3                                                    as institutional_k,
  round(100.0 * a.retail / nullif(a.retail + a.instit, 0), 1)       as retail_pct,
  a.n_funds                                                         as n_funds,
  a.n_funds_with_split                                              as n_funds_with_split
from months m
left join agg a on a.period = m.period
order by m.period
